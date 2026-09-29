"""
跨模型领域规则验证（真实 PostgreSQL 约束一并测试）：
跨年卷、停刊月份、两期合刊、缺号 vs 缺藏、装订/拆订、
以及“一个条码不能隐含覆盖多个期号”的数据库级不变量。
"""
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from serials.models import BoundVolume, Issue, PieceIssue, Serial
from serials import services


def make_serial():
    return Serial.objects.create(title="博览月刊", issn="1001-000X")


def make_issue(serial, volume, no, y, m, **kw):
    return Issue.objects.create(
        serial=serial, volume=volume, issue_no=no,
        pub_year=y, pub_month=m, **kw)


class CrossYearAndCeasedTests(TestCase):
    def setUp(self):
        self.serial = make_serial()
        # 跨年卷：第55卷覆盖 2023-07 .. 2024-06
        make_issue(self.serial, 55, 1, 2023, 7)
        make_issue(self.serial, 55, 6, 2024, 1)
        make_issue(self.serial, 55, 12, 2024, 6)
        # 2023-09 停刊（不占期号）
        Issue.objects.create(
            serial=self.serial, volume=None, issue_no=None,
            pub_year=2023, pub_month=9, issue_type=Issue.CEASED,
            note="暑期休刊")

    def test_cross_year_volume_flag(self):
        tl = services.build_timeline(self.serial)
        v55 = next(v for v in tl["volumes"] if v["volume"] == 55)
        self.assertTrue(v55["is_cross_year"])
        self.assertEqual(v55["pub_years"], [2023, 2024])

    def test_ceased_month_separated_from_cells(self):
        tl = services.build_timeline(self.serial)
        v55 = next(v for v in tl["volumes"] if v["volume"] == 55)
        # 停刊月份不出现在卷格子里
        self.assertEqual(
            {c["issue_no"] for c in v55["cells"]}, {1, 6, 12})
        self.assertEqual(
            [c["label"] for c in tl["ceased_months"]], ["2023-09"])

    def test_ceased_month_not_treated_as_month_gap(self):
        tl = services.build_timeline(self.serial)
        v55 = next(v for v in tl["volumes"] if v["volume"] == 55)
        # 2023-08 没有期号也没有停刊 → 月份缺口
        self.assertIn("2023-08", v55["month_gaps"])
        # 2023-09 有停刊记录 → 不算月份缺口
        self.assertNotIn("2023-09", v55["month_gaps"])

    def test_ceased_issue_has_no_piece_and_locate_says_ceased(self):
        ceased = Issue.objects.get(issue_type=Issue.CEASED)
        result = services.locate_issue(ceased)
        self.assertEqual(result.location_kind, "ceased")
        self.assertIsNone(result.piece)


class NumberingGapVsMissingHoldingsTests(TestCase):
    def setUp(self):
        self.serial = make_serial()
        make_issue(self.serial, 56, 1, 2024, 7)
        make_issue(self.serial, 56, 2, 2024, 8)
        # 第3期完全没有发行记录（缺号）
        i4 = make_issue(self.serial, 56, 4, 2024, 10)
        # 第1、2期入藏，第4期不入藏（缺藏）
        services.check_in_issues(
            serial=self.serial, issue_ids=[
                Issue.objects.get(volume=56, issue_no=1).id],
            barcode="B1", call_number="Q/1", location="架A")
        services.check_in_issues(
            serial=self.serial, issue_ids=[
                Issue.objects.get(volume=56, issue_no=2).id],
            barcode="B2", call_number="Q/2", location="架A")
        self.issue4 = i4

    def test_missing_number_is_gap_not_claim(self):
        tl = services.build_timeline(self.serial)
        v56 = next(v for v in tl["volumes"] if v["volume"] == 56)
        self.assertEqual(v56["numbering_gaps"], [3])
        # 缺号不出现在缺藏清单
        self.assertNotIn("第56卷第3期", v56["unheld"])

    def test_existing_issue_without_piece_is_unheld_not_gap(self):
        tl = services.build_timeline(self.serial)
        v56 = next(v for v in tl["volumes"] if v["volume"] == 56)
        self.assertIn("第56卷第4期", v56["unheld"])
        self.assertNotIn(4, v56["numbering_gaps"])

    def test_locate_unheld(self):
        result = services.locate_issue(self.issue4)
        self.assertEqual(result.location_kind, "not_held")
        self.assertIn("有发行记录但无实体", result.location)


class CombinedIssueTests(TestCase):
    def setUp(self):
        self.serial = make_serial()
        group = "v55-n7-n8"
        self.i7 = make_issue(self.serial, 55, 7, 2024, 2,
                             issue_type=Issue.COMBINED,
                             combined_group=group)
        self.i8 = make_issue(self.serial, 55, 8, 2024, 2,
                             issue_type=Issue.COMBINED,
                             combined_group=group)

    def test_partial_group_checkin_rejected(self):
        with self.assertRaises(services.RegistrationError):
            services.check_in_issues(
                serial=self.serial, issue_ids=[self.i7.id],
                barcode="BC", call_number="Q/7-8", location="架A")

    def test_one_piece_two_explicit_links(self):
        piece, created = services.check_in_issues(
            serial=self.serial, issue_ids=[self.i7.id, self.i8.id],
            barcode="BC-55-78", call_number="Q/BL/55/7-8",
            location="现刊架-A12")
        self.assertTrue(created)
        links = PieceIssue.objects.filter(piece=piece).order_by("order")
        # 关键：一个条码下有两条显式期号关联，而不是一个字段盖住两期
        self.assertEqual(list(links.values_list("issue_id", flat=True)),
                         [self.i7.id, self.i8.id])

    def test_locate_from_either_issue_returns_same_piece(self):
        piece, _ = services.check_in_issues(
            serial=self.serial, issue_ids=[self.i7.id, self.i8.id],
            barcode="BC-55-78", call_number="Q/BL/55/7-8",
            location="现刊架-A12")
        for issue in (self.i7, self.i8):
            r = services.locate_issue(issue)
            self.assertEqual(r.piece["barcode"], "BC-55-78")
            self.assertEqual(r.location_kind, "piece")
            # 实体上可见它覆盖的全部期号
            self.assertEqual(set(r.piece["covers_citations"]),
                             {"第55卷第7期", "第55卷第8期"})

    def test_database_blocks_two_pieces_covering_one_issue(self):
        """数据库级不变量：同一期号不能被两个实体覆盖。"""
        services.check_in_issues(
            serial=self.serial, issue_ids=[self.i7.id, self.i8.id],
            barcode="BC-1", call_number="Q/7-8", location="架A")
        other_piece = services.check_in_issues(
            serial=self.serial,
            issue_ids=[make_issue(
                self.serial, 55, 9, 2024, 3).id],
            barcode="BC-9", call_number="Q/9", location="架A")[0]
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PieceIssue.objects.create(piece=other_piece,
                                          issue=self.i7)


class BindUnbindTests(TestCase):
    def setUp(self):
        self.serial = make_serial()
        self.i1 = make_issue(self.serial, 55, 1, 2023, 7)
        group = "v55-n7-n8"
        self.i7 = make_issue(self.serial, 55, 7, 2024, 2,
                             issue_type=Issue.COMBINED,
                             combined_group=group)
        self.i8 = make_issue(self.serial, 55, 8, 2024, 2,
                             issue_type=Issue.COMBINED,
                             combined_group=group)
        self.p1 = services.check_in_issues(
            serial=self.serial, issue_ids=[self.i1.id],
            barcode="BC-55-01", call_number="Q/BL/55/1",
            location="现刊架-A12")[0]
        self.p78 = services.check_in_issues(
            serial=self.serial, issue_ids=[self.i7.id, self.i8.id],
            barcode="BC-55-78", call_number="Q/BL/55/7-8",
            location="现刊架-A12")[0]

    def test_bind_then_locate_any_issue_finds_volume(self):
        volume = services.bind_pieces(
            piece_ids=[self.p1.id, self.p78.id],
            call_number="Q/BL/55-BD", barcode="BD-55",
            title_display="第55卷合订本(2023-2024)",
            location="密排库A-01-03", operator="tester")
        # 从普通期和合刊的“任一期号”都能找到装订册
        for issue in (self.i1, self.i7, self.i8):
            r = services.locate_issue(issue)
            self.assertEqual(r.location_kind, "bound")
            self.assertEqual(r.bound_volume["call_number"],
                             "Q/BL/55-BD")
            self.assertEqual(r.location, "密排库A-01-03（Q/BL/55-BD 内）")
        self.assertEqual(BoundVolume.objects.count(), 1)
        self.assertEqual(volume.pieces.count(), 2)

    def test_unbind_restores_each_own_location(self):
        volume = services.bind_pieces(
            piece_ids=[self.p1.id, self.p78.id],
            call_number="Q/BL/55-BD", barcode="BD-55",
            title_display="第55卷合订本",
            location="密排库A-01-03")
        services.unbind_volume(volume_id=volume.id)

        r1 = services.locate_issue(self.i1)
        r7 = services.locate_issue(self.i7)
        self.assertEqual(r1.location_kind, "piece")
        self.assertEqual(r7.location_kind, "piece")
        # 各自恢复到装订前位置
        self.assertEqual(r1.location, "现刊架-A12")
        self.assertEqual(r7.location, "现刊架-A12")
        volume.refresh_from_db()
        self.assertFalse(volume.is_bound)
        self.p1.refresh_from_db()
        self.assertIsNone(self.p1.bound_volume_id)
        self.assertEqual(self.p1.location_before_binding, "")

    def test_cannot_double_bind(self):
        services.bind_pieces(
            piece_ids=[self.p1.id, self.p78.id],
            call_number="Q/BL/55-BD", barcode="BD-55",
            title_display="卷55", location="库1")
        with self.assertRaises(services.RegistrationError):
            services.bind_pieces(
                piece_ids=[self.p1.id],
                call_number="Q/BL/55-BD2", barcode="BD-56",
                title_display="再订", location="库2")

    def test_cannot_mix_serials_in_one_volume(self):
        other = make_serial()
        oi = make_issue(other, 1, 1, 2024, 1)
        p_other = services.check_in_issues(
            serial=other, issue_ids=[oi.id],
            barcode="BC-OTHER", call_number="X/1", location="架B")[0]
        with self.assertRaises(services.RegistrationError):
            services.bind_pieces(
                piece_ids=[self.p1.id, p_other.id],
                call_number="Q/MIX", barcode="BD-MIX",
                title_display="混订", location="库1")
