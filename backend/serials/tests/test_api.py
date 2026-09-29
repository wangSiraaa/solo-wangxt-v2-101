"""API 端到端验证：检索、入藏、装订、拆订走真实 HTTP 层。"""
import json

from django.test import TestCase
from rest_framework.test import APIClient

from serials.models import Issue, Serial


class ApiFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        r = self.client.post(
            "/api/serials/",
            {"title": "博览月刊", "issn": "1001-000X"}, format="json")
        self.serial_id = r.data["id"]

        # 两期合刊（书目层）
        r = self.client.post(
            "/api/serials/combined_group/",
            {"serial": self.serial_id, "volume": 55,
             "group": "v55-n7-n8",
             "entries": [
                 {"issue_no": 7, "pub_year": 2024, "pub_month": 2},
                 {"issue_no": 8, "pub_year": 2024, "pub_month": 2}]},
            format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(r.data), 2)
        self.issue7_id, self.issue8_id = [d["id"] for d in r.data]

        # 普通期（跨年卷 2023 年侧）
        r = self.client.post(
            "/api/issues/",
            {"serial": self.serial_id, "volume": 55, "issue_no": 1,
             "pub_year": 2023, "pub_month": 7,
             "issue_type": "normal"}, format="json")
        self.issue1_id = r.data["id"]

        # 停刊月份
        r = self.client.post(
            "/api/issues/",
            {"serial": self.serial_id, "volume": None, "issue_no": None,
             "pub_year": 2023, "pub_month": 9,
             "issue_type": "ceased", "note": "暑期休刊"},
            format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_timeline_has_cross_year_and_ceased(self):
        r = self.client.get(f"/api/serials/{self.serial_id}/timeline/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        v55 = next(v for v in data["volumes"] if v["volume"] == 55)
        self.assertTrue(v55["is_cross_year"])
        self.assertEqual(v55["pub_years"], [2023, 2024])
        self.assertEqual(data["ceased_months"][0]["label"], "2023-09")
        # 合刊格子相互标注
        cell7 = next(c for c in v55["cells"] if c["issue_no"] == 7)
        self.assertEqual(cell7["combined_with"], [8])
        # 尚未入藏
        self.assertFalse(cell7["held"])

    def test_checkin_combo_rejects_single_barcode_without_both_issues(self):
        r = self.client.post(
            f"/api/serials/{self.serial_id}/check_in/",
            {"issue_ids": [self.issue7_id],
             "barcode": "BC-55-78", "call_number": "Q/7-8",
             "location": "现刊架"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("合刊必须整组入藏", json.dumps(r.data, ensure_ascii=False))

    def test_full_locate_bind_unbind_flow(self):
        # 合刊整组入藏
        r = self.client.post(
            f"/api/serials/{self.serial_id}/check_in/",
            {"issue_ids": [self.issue7_id, self.issue8_id],
             "barcode": "BC-55-78", "call_number": "Q/BL/55/7-8",
             "location": "现刊架-A12"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        combo_piece_id = r.data["id"]
        # 两条显式关联
        self.assertEqual(
            {pi["issue_id"] for pi in r.data["piece_issues"]},
            {self.issue7_id, self.issue8_id})

        # 普通期入藏
        r = self.client.post(
            f"/api/serials/{self.serial_id}/check_in/",
            {"issue_ids": [self.issue1_id],
             "barcode": "BC-55-01", "call_number": "Q/BL/55/1",
             "location": "现刊架-A12"}, format="json")
        piece1_id = r.data["id"]

        # 按卷期检索：合刊第7期、第8期都定位到同一实体
        for no in (7, 8):
            r = self.client.get(
                f"/api/locate/?serial={self.serial_id}"
                f"&volume=55&issue_no={no}")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data["piece"]["barcode"], "BC-55-78")
            self.assertEqual(r.data["location"], "现刊架-A12")

        # 按发行年月检索（编号与年月分开）
        r = self.client.get(
            f"/api/locate/?serial={self.serial_id}&year=2023&month=7")
        self.assertEqual(r.data["issue"]["citation"], "第55卷第1期")

        # 缺号检索返回 404 且明确不等于缺藏
        r = self.client.get(
            f"/api/locate/?serial={self.serial_id}"
            f"&volume=55&issue_no=10")
        self.assertEqual(r.status_code, 404)
        self.assertIn("缺号", json.dumps(r.data, ensure_ascii=False))

        # 装订
        r = self.client.post(
            "/api/bound-volumes/bind/",
            {"piece_ids": [piece1_id, combo_piece_id],
             "call_number": "Q/BL/55-BD", "barcode": "BD-55",
             "title_display": "博览月刊第55卷(2023-2024)",
             "location": "密排库A-01-03"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        volume_id = r.data["id"]

        # 装订后从任一期号找到册
        for no in (1, 7, 8):
            r = self.client.get(
                f"/api/locate/?serial={self.serial_id}"
                f"&volume=55&issue_no={no}")
            self.assertEqual(r.data["location_kind"], "bound")
            self.assertEqual(r.data["bound_volume"]["call_number"],
                             "Q/BL/55-BD")

        # 拆订
        r = self.client.post(
            f"/api/bound-volumes/{volume_id}/unbind/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        # 恢复各自位置
        r = self.client.get(
            f"/api/locate/?serial={self.serial_id}"
            f"&volume=55&issue_no=8")
        self.assertEqual(r.data["location_kind"], "piece")
        self.assertEqual(r.data["location"], "现刊架-A12")

    def test_second_checkin_of_same_issue_rejected(self):
        self.client.post(
            f"/api/serials/{self.serial_id}/check_in/",
            {"issue_ids": [self.issue7_id, self.issue8_id],
             "barcode": "BC-A", "call_number": "Q/A",
             "location": "架A"}, format="json")
        r = self.client.post(
            f"/api/serials/{self.serial_id}/check_in/",
            {"issue_ids": [self.issue7_id, self.issue8_id],
             "barcode": "BC-B", "call_number": "Q/B",
             "location": "架B"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("已有在藏实体", json.dumps(r.data, ensure_ascii=False))
