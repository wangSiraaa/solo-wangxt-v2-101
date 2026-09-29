"""
领域服务：入藏（check_in）、装订（bind）、拆订（unbind）、
定位（locate）与时间轴（timeline）构建。

所有跨模型的一致性规则集中在这里，视图只做参数装配。
"""
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

from .models import BoundVolume, BindingEvent, Issue, Piece, PieceIssue


class RegistrationError(Exception):
    """业务规则冲突（HTTP 400 级别的领域错误）。"""


# ---------------------------------------------------------------------------
# 入藏
# ---------------------------------------------------------------------------

def _find_piece(serial, barcode=None, call_number=None, location=None):
    """按条码定位已存在的 Piece（同一次合刊入藏第二次调用时复用）。"""
    if barcode:
        return Piece.objects.filter(
            serial=serial, barcode=barcode).first()
    return None


@transaction.atomic
def check_in_issues(*, serial, issue_ids, barcode, call_number, location,
                    allow_add_to_existing=False):
    """
    将一个或多个期号入藏到同一个物理 Piece。

    - 普通期：issue_ids 传 1 个；
    - 两期合刊：issue_ids 传同合刊组的 2 个（或更多），
      系统逐行写 PieceIssue —— 一个条码下的每个期号都可单独检索；
    - 任一期号若已在别的 Piece 上，拒绝（uniq_one_piece_per_issue
      会兜底，这里给出清晰错误）。
    """
    issues = list(Issue.objects.filter(
        pk__in=issue_ids, serial=serial,
        issue_type__in=[Issue.NORMAL, Issue.COMBINED]))
    if len(issues) != len(set(issue_ids)):
        raise RegistrationError("存在无效或不属于该刊的期号")
    if not issues:
        raise RegistrationError("至少选择一个可入藏的期号")

    held = {pi.issue_id for pi in PieceIssue.objects.filter(
        issue__in=issues).select_related("piece")}
    if held:
        cites = "、".join(
            i.citation() for i in issues if i.id in held)
        raise RegistrationError(f"以下期号已有在藏实体：{cites}")

    # 合刊组一致性检查：合刊期必须与同组期一起入藏
    groups = {i.combined_group for i in issues if i.is_combined}
    for group in groups:
        if not group:
            raise RegistrationError("合刊期缺少合刊组标识")
        siblings = Issue.objects.filter(
            serial=serial, combined_group=group,
            issue_type=Issue.COMBINED)
        sibling_ids = set(siblings.values_list("id", flat=True))
        if not sibling_ids.issubset(set(issue_ids)):
            missing = siblings.exclude(pk__in=issue_ids)
            cites = "、".join(i.citation() for i in missing)
            raise RegistrationError(
                f"合刊必须整组入藏，还缺：{cites}")
        # 不允许把普通期与不相关合刊混进同一实体
        unrelated = [i for i in issues
                     if not i.is_combined
                     or i.combined_group != group]
        if len(groups) > 1:
            raise RegistrationError("一个实体不能混入两个合刊组")
        if unrelated:
            raise RegistrationError(
                "合刊实体只能包含同一合刊组的期号")

    piece, created = Piece.objects.get_or_create(
        serial=serial, barcode=barcode,
        defaults={"call_number": call_number, "location": location})
    if not created and not allow_add_to_existing:
        raise RegistrationError(f"条码 {barcode} 已存在")
    if not created:
        if piece.bound_volume_id:
            raise RegistrationError("该实体已装订，不能直接追加期号")
        piece.call_number = call_number
        piece.location = location
        piece.save(update_fields=["call_number", "location"])

    for order, issue in enumerate(
            sorted(issues, key=lambda i: (i.volume or 0, i.issue_no or 0))):
        PieceIssue.objects.create(piece=piece, issue=issue, order=order)
    return piece, created


# ---------------------------------------------------------------------------
# 装订 / 拆订
# ---------------------------------------------------------------------------

@transaction.atomic
def bind_pieces(*, piece_ids, call_number, barcode, title_display,
                location, operator=""):
    """
    把多个散置 Piece 装订成一册 BoundVolume。

    装订后：
    - 每个 Piece 记住自己装订前的位置（供拆订恢复）；
    - 实际位置统一为合订本位置；
    - 期号 -> Piece -> BoundVolume 的检索链不受影响。
    """
    pieces = list(Piece.objects.filter(pk__in=piece_ids))
    if len(pieces) != len(set(piece_ids)):
        raise RegistrationError("存在无效实体")
    already = [p for p in pieces if p.bound_volume_id is not None]
    if already:
        raise RegistrationError(
            "实体已在装订册中：" + "、".join(p.barcode for p in already))
    serials = {p.serial_id for p in pieces}
    if len(serials) > 1:
        raise RegistrationError("不同期刊的实体不能装订到同一册")

    volume = BoundVolume.objects.create(
        call_number=call_number, barcode=barcode,
        title_display=title_display, location=location, is_bound=True)
    from django.utils import timezone
    volume.bound_at = timezone.now()
    volume.save(update_fields=["bound_at"])

    for order, piece in enumerate(
            sorted(pieces,
                   key=lambda p: (
                       min((pi.issue.volume or 0)
                           for pi in p.piece_issues.select_related("issue")),
                       min((pi.issue.issue_no or 0)
                           for pi in p.piece_issues.select_related("issue")),
                       p.bind_order))):
        before = piece.location
        piece.location_before_binding = before
        piece.bound_volume = volume
        piece.bind_order = order
        piece.save(update_fields=[
            "location_before_binding", "bound_volume", "bind_order"])
        BindingEvent.objects.create(
            event_type=BindingEvent.BIND, piece=piece,
            bound_volume=volume, location_from=before,
            location_to=location, operator=operator)
    return volume


@transaction.atomic
def unbind_volume(*, volume_id, operator=""):
    """
    拆订：每个 Piece 恢复各自装订前的位置，BoundVolume 标记为已拆。
    各期号重新指向散置 Piece 的自身位置。
    """
    volume = BoundVolume.objects.filter(pk=volume_id).first()
    if volume is None:
        raise RegistrationError("装订册不存在")
    if not volume.is_bound:
        raise RegistrationError("该册已经处于拆订状态")

    pieces = list(Piece.objects.filter(bound_volume=volume))
    for piece in pieces:
        restored = piece.location_before_binding or piece.location
        BindingEvent.objects.create(
            event_type=BindingEvent.UNBIND, piece=piece,
            bound_volume=volume, location_from=volume.location,
            location_to=restored, operator=operator)
        piece.bound_volume = None
        piece.bind_order = 0
        piece.location = restored
        piece.location_before_binding = ""
        piece.save(update_fields=[
            "bound_volume", "bind_order", "location",
            "location_before_binding"])
    volume.is_bound = False
    volume.save(update_fields=["is_bound"])
    return volume


# ---------------------------------------------------------------------------
# 定位
# ---------------------------------------------------------------------------

@dataclass
class LocationResult:
    issue: dict
    piece: dict | None
    bound_volume: dict | None
    location: str
    location_kind: str  # bound / piece / not_held / ceased / no_record

    def as_dict(self):
        return {
            "issue": self.issue,
            "piece": self.piece,
            "bound_volume": self.bound_volume,
            "location": self.location,
            "location_kind": self.location_kind,
        }


def locate_issue(issue):
    """
    给定任一期号（含合刊中的任意一期），找到它当前所在。

    检索链：Issue -> PieceIssue -> Piece -> BoundVolume。
    这保证合刊装订后仍可从“任一期号”找到册，拆订后回到 Piece 位置。
    """
    issue_d = {
        "id": issue.id,
        "citation": issue.citation(),
        "pub_label": issue.pub_label(),
        "issue_type": issue.issue_type,
    }
    if issue.is_ceased:
        return LocationResult(issue_d, None, None,
                              "—（停刊月份，无实体）", "ceased")

    link = (PieceIssue.objects
            .filter(issue=issue)
            .select_related("piece", "piece__bound_volume")
            .first())
    if link is None:
        return LocationResult(issue_d, None, None,
                              "未入藏（有发行记录但无实体）", "not_held")

    piece = link.piece
    piece_d = {
        "id": piece.id,
        "barcode": piece.barcode,
        "call_number": piece.call_number,
        "location": piece.location,
        "is_bound": piece.is_bound,
        "covers_citations": [
            pi.issue.citation()
            for pi in piece.piece_issues.select_related("issue")],
    }
    if piece.bound_volume_id and piece.bound_volume.is_bound:
        bv = piece.bound_volume
        bv_d = {
            "id": bv.id,
            "call_number": bv.call_number,
            "barcode": bv.barcode,
            "title_display": bv.title_display,
            "location": bv.location,
        }
        return LocationResult(issue_d, piece_d, bv_d,
                              f"{bv.location}（{bv.call_number} 内）",
                              "bound")
    return LocationResult(issue_d, piece_d, None, piece.location, "piece")


# ---------------------------------------------------------------------------
# 时间轴
# ---------------------------------------------------------------------------

def _month_key(year, month):
    return year * 12 + (month or 0)


def build_timeline(serial):
    """
    构建按卷组织的时间轴。

    每个卷返回：
    - cells: 有期号记录的格子（普通期/合刊期，含实体与位置信息）；
    - numbering_gaps: 卷内缺失的期号 —— 只表示“没有发行记录”；
    - month_gaps: 该卷覆盖的连续月份中没有任何期号、也没有停刊记录
      的月份（同样只是无发行记录）；
    - ceased_months: 停刊/休刊月份；
    - unheld: 有发行记录但当前无实体的期号（缺藏）。

    “缺号”和“缺藏”严格分开。
    """
    issues_qs = (serial.issues
                 .prefetch_related(
                     "piece_issues__piece__bound_volume")
                 .order_by("volume", "issue_no", "pub_year", "pub_month"))
    issues = list(issues_qs)
    by_volume: dict[int | None, list] = defaultdict(list)
    ceased_months = []
    for issue in issues:
        if issue.is_ceased:
            ceased_months.append(issue)
        else:
            by_volume[issue.volume].append(issue)

    volumes_out = []
    for volume in sorted(v for v in by_volume if v is not None):
        vissues = by_volume[volume]
        # 用 PieceIssue 缓存建立 issue_id -> 定位
        loc_map = {}
        for issue in vissues:
            links = [pi for pi in issue.piece_issues.all()]
            loc_map[issue.id] = links[0] if links else None

        # --- 期号缺号：1..max 中没有发行记录的编号 ---
        present_nos = {i.issue_no for i in vissues}
        max_no = max(present_nos)
        numbering_gaps = [n for n in range(1, max_no + 1)
                          if n not in present_nos]

        # --- 月份缺口：卷覆盖月份连续区间内既无期号也无停刊记录 ---
        dated = [i for i in vissues if i.pub_month]
        month_gaps = []
        if dated:
            lo = min(_month_key(i.pub_year, i.pub_month) for i in dated)
            hi = max(_month_key(i.pub_year, i.pub_month) for i in dated)
            occupied = {_month_key(i.pub_year, i.pub_month) for i in dated}
            ceased_keys = {
                _month_key(i.pub_year, i.pub_month)
                for i in ceased_months if i.pub_month}
            for key in range(lo, hi + 1):
                if key in occupied:
                    continue
                y, m = divmod(key, 12)
                if key in ceased_keys:
                    continue
                month_gaps.append(
                    f"{y}-{m:02d}" if m else f"{y}（月份缺失）")

        # --- 格子 ---
        groups_seen = {}
        cells = []
        unheld = []
        for issue in vissues:
            link = loc_map[issue.id]
            held = link is not None
            bound = False
            bound_info = None
            piece_info = None
            location = None
            if held:
                piece = link.piece
                piece_info = {
                    "barcode": piece.barcode,
                    "call_number": piece.call_number,
                }
                if piece.bound_volume_id and piece.bound_volume.is_bound:
                    bound = True
                    bv = piece.bound_volume
                    bound_info = {
                        "call_number": bv.call_number,
                        "title_display": bv.title_display,
                        "location": bv.location,
                    }
                    location = f"{bv.location}（{bv.call_number}）"
                else:
                    location = piece.location
            else:
                unheld.append(issue.citation())

            cell = {
                "issue_id": issue.id,
                "volume": issue.volume,
                "issue_no": issue.issue_no,
                "pub_label": issue.pub_label(),
                "citation": issue.citation(),
                "issue_type": issue.issue_type,
                "combined_group": issue.combined_group,
                "held": held,
                "bound": bound,
                "location": location,
                "piece": piece_info,
                "bound_volume": bound_info,
                "note": issue.note,
            }
            cells.append(cell)
            if issue.is_combined:
                groups_seen.setdefault(
                    issue.combined_group, []).append(cell)

        # 标记合刊同组（前端画“跨格”用）
        for group, members in groups_seen.items():
            for c in members:
                c["combined_with"] = sorted(
                    m["issue_no"] for m in members if m is not c)

        pub_years = sorted({i.pub_year for i in vissues})
        volumes_out.append({
            "volume": volume,
            "pub_years": pub_years,  # 跨年卷时长度 > 1
            "is_cross_year": len(pub_years) > 1,
            "cells": cells,
            "numbering_gaps": numbering_gaps,
            "month_gaps": month_gaps,
            "unheld": unheld,
        })

    return {
        "serial": {
            "id": serial.id,
            "title": serial.title,
            "issn": serial.issn,
            "publisher": serial.publisher,
        },
        "volumes": volumes_out,
        "ceased_months": [
            {"id": i.id, "label": i.pub_label(), "note": i.note}
            for i in sorted(ceased_months,
                            key=lambda x: (x.pub_year, x.pub_month or 0))
        ],
        "legend": {
            "normal": "普通期（有发行记录）",
            "combined": "合刊期（与同组期共用一个实体，期号各自可检）",
            "ceased": "停刊月份（不出版，无实体预期）",
            "numbering_gaps": "缺号：无发行记录，不自动等同缺藏",
            "month_gaps": "月份缺口：无发行记录也无停刊记录",
            "unheld": "缺藏：有发行记录但无实体",
        },
    }
