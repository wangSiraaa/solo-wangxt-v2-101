"""
灌入演示数据（幂等：重复执行会先清掉旧的演示刊）。

样例布局：《博览月刊》
- 第55卷是跨年卷：2023-07 ~ 2024-06
    第1期 2023-07 ... 第5期 2023-12（第5期有发行记录但不入藏＝缺藏）
    2023-09 停刊月份（不出版；不占期号）
    第7-8期 两期合刊（2024-02，一个实体显式关联两个期号）
    第9~12期 2024-03 ~ 2024-06
- 第56卷：2024-07 起
    第1、2、4期有发行记录（第3期无发行记录＝缺号）
    第4期有发行记录但不入藏＝缺藏（与缺号严格区分）
- 第55卷各实体装订为一册合订本，验证“装订后从任一期号找册”。
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from serials.models import BoundVolume, Issue, Piece, Serial
from serials.services import bind_pieces, check_in_issues


DEMO_TITLE = "博览月刊"
DEMO_LOC = "现刊架-A12"
BOUND_LOC = "密排库A-01-03"


class Command(BaseCommand):
    help = "创建跨年卷/停刊/两期合刊演示数据"

    @transaction.atomic
    def handle(self, *args, **options):
        Serial.objects.filter(title=DEMO_TITLE).delete()
        # 合订本不直接挂刊，按演示命名规则清理（幂等重跑）
        BoundVolume.objects.filter(
            call_number__startswith="Q/BL/55-BD").delete()

        serial = Serial.objects.create(
            title=DEMO_TITLE, issn="1001-000X",
            publisher="示例出版社",
            note="连续出版物登记演示刊")

        # ---- 第55卷（跨年卷 2023-07 ~ 2024-06）----
        plan_2023 = {
            1: (2023, 7), 2: (2023, 8),
            # 2023-09 停刊
            3: (2023, 10), 4: (2023, 11), 5: (2023, 12),
        }
        plan_2024 = {
            6: (2024, 1),
            # 7、8 合刊，发行日期统一记 2024-02
            9: (2024, 3), 10: (2024, 4), 11: (2024, 5), 12: (2024, 6),
        }
        for no, (y, m) in {**plan_2023, **plan_2024}.items():
            Issue.objects.create(
                serial=serial, volume=55, issue_no=no,
                pub_year=y, pub_month=m, issue_type=Issue.NORMAL)

        Issue.objects.create(
            serial=serial, volume=None, issue_no=None,
            pub_year=2023, pub_month=9, issue_type=Issue.CEASED,
            note="暑期休刊一月")

        group = "v55-n7-n8"
        for no in (7, 8):
            Issue.objects.create(
                serial=serial, volume=55, issue_no=no,
                pub_year=2024, pub_month=2,
                issue_type=Issue.COMBINED, combined_group=group,
                note="7-8期合刊")

        # ---- 第56卷：缺号（第3期）与缺藏（第4期）对照 ----
        for no, m in ((1, 7), (2, 8), (4, 10)):
            Issue.objects.create(
                serial=serial, volume=56, issue_no=no,
                pub_year=2024, pub_month=m, issue_type=Issue.NORMAL,
                note=("本期未出版" if no == 2 else ""))

        # ---- 入藏：第55卷（第5期故意不入藏＝缺藏）----
        held_nos = [1, 2, 3, 4, 6, 9, 10, 11, 12]
        pieces_55 = []
        for no in held_nos:
            issue = Issue.objects.get(serial=serial, volume=55,
                                      issue_no=no)
            piece, _ = check_in_issues(
                serial=serial, issue_ids=[issue.id],
                barcode=f"BC-55-{no:02d}",
                call_number=f"Q/BL/55/{no}",
                location=DEMO_LOC)
            pieces_55.append(piece)

        # 合刊：一个实体、逐行关联两个期号（不是一个条码“盖住”两期）
        combo = Issue.objects.filter(serial=serial, volume=55,
                                     combined_group=group)
        combo_piece, _ = check_in_issues(
            serial=serial, issue_ids=[i.id for i in combo],
            barcode="BC-55-78", call_number="Q/BL/55/7-8",
            location=DEMO_LOC)
        pieces_55.append(combo_piece)

        # 第56卷：第1、2期入藏；第4期有发行记录但不入藏
        for no in (1, 2):
            issue = Issue.objects.get(serial=serial, volume=56,
                                      issue_no=no)
            check_in_issues(
                serial=serial, issue_ids=[issue.id],
                barcode=f"BC-56-{no:02d}",
                call_number=f"Q/BL/56/{no}",
                location=DEMO_LOC)

        # ---- 装订第55卷 ----
        bind_pieces(
            piece_ids=[p.id for p in pieces_55],
            call_number="Q/BL/55-BD", barcode="BD-55",
            title_display="博览月刊 第55卷合订本（2023-2024）",
            location=BOUND_LOC, operator="demo")

        self.stdout.write(self.style.SUCCESS(
            f"演示数据已创建：{serial.title}（id={serial.id}）"))
        self.stdout.write(
            "  第55卷跨年（2023-07~2024-06），含2023-09停刊、"
            "7-8期合刊，已装订为 Q/BL/55-BD")
        self.stdout.write(
            "  第55卷第5期：缺藏（有发行记录无实体）")
        self.stdout.write(
            "  第56卷第3期：缺号（无发行记录）；第4期：缺藏")
