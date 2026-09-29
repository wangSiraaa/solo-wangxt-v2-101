from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BoundVolume, Issue, Piece, Serial
from .serializers import (
    BindSerializer, BoundVolumeSerializer, CheckInSerializer,
    CombinedGroupCreateSerializer, IssueSerializer, PieceSerializer,
    SerialSerializer,
)
from . import services


class SerialViewSet(viewsets.ModelViewSet):
    queryset = Serial.objects.all()
    serializer_class = SerialSerializer

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """GET /api/serials/{id}/timeline/ —— 馆员时间轴。"""
        serial = self.get_object()
        return Response(services.build_timeline(serial))

    @action(detail=True, methods=["post"])
    def check_in(self, request, pk=None):
        """POST /api/serials/{id}/check_in/ —— 期号入藏为实体。"""
        serial = self.get_object()
        payload = dict(request.data)
        payload["serial"] = serial.pk
        serializer = CheckInSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            piece, created = services.check_in_issues(
                serial=serial,
                issue_ids=data["issue_ids"],
                barcode=data["barcode"],
                call_number=data["call_number"],
                location=data["location"])
        except services.RegistrationError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(
            PieceSerializer(piece).data,
            status=status.HTTP_201_CREATED if created
            else status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def combined_group(self, request):
        """POST /api/serials/combined_group/ —— 登记两期合刊（书目层）。"""
        serializer = CombinedGroupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        import uuid
        group = data.get("group") or f"G{uuid.uuid4().hex[:10]}"
        if Issue.objects.filter(serial=data["serial"],
                                combined_group=group).exists():
            return Response({"detail": "合刊组标识已存在"},
                            status=status.HTTP_400_BAD_REQUEST)
        created = []
        for entry in data["entries"]:
            issue = Issue.objects.create(
                serial=data["serial"], volume=data["volume"],
                issue_no=entry["issue_no"],
                pub_year=entry["pub_year"],
                pub_month=entry["pub_month"],
                issue_type=Issue.COMBINED,
                combined_group=group,
                note=data.get("note", ""))
            created.append(issue)
        return Response(IssueSerializer(created, many=True).data,
                        status=status.HTTP_201_CREATED)


class IssueViewSet(viewsets.ModelViewSet):
    """
    期号检索：
    - ?serial=<id>&volume=&issue_no= 按卷期精确查；
    - ?year=&month= 按发行年月查（编号与年月分离，两条检索路径）；
    - ?q=3-4 可查合刊引用文本。
    """

    queryset = Issue.objects.select_related("serial")
    serializer_class = IssueSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("serial"):
            qs = qs.filter(serial_id=params["serial"])
        if params.get("volume"):
            qs = qs.filter(volume=params["volume"])
        if params.get("issue_no"):
            qs = qs.filter(issue_no=params["issue_no"])
        if params.get("year"):
            qs = qs.filter(pub_year=params["year"])
        if params.get("month"):
            qs = qs.filter(pub_month=params["month"])
        if params.get("type"):
            qs = qs.filter(issue_type=params["type"])
        q = params.get("q")
        if q:
            qs = qs.filter(
                Q(serial__title__icontains=q)
                | Q(note__icontains=q)
                | Q(combined_group__icontains=q))
        return qs


class PieceViewSet(viewsets.ModelViewSet):
    queryset = Piece.objects.prefetch_related(
        "piece_issues__issue", "bound_volume")
    serializer_class = PieceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("serial"):
            qs = qs.filter(serial_id=params["serial"])
        if params.get("barcode"):
            qs = qs.filter(barcode=params["barcode"])
        if params.get("bound") == "true":
            qs = qs.filter(bound_volume__isnull=False)
        if params.get("bound") == "false":
            qs = qs.filter(bound_volume__isnull=True)
        return qs


class BoundVolumeViewSet(viewsets.ModelViewSet):
    queryset = BoundVolume.objects.prefetch_related(
        "pieces__piece_issues__issue")
    serializer_class = BoundVolumeSerializer

    @action(detail=False, methods=["post"])
    def bind(self, request):
        """POST /api/bound-volumes/bind/ —— 装订。"""
        serializer = BindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            volume = services.bind_pieces(
                piece_ids=data["piece_ids"],
                call_number=data["call_number"],
                barcode=data["barcode"],
                title_display=data["title_display"],
                location=data["location"],
                operator=data.get("operator", ""))
        except services.RegistrationError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(BoundVolumeSerializer(volume).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def unbind(self, request, pk=None):
        """POST /api/bound-volumes/{id}/unbind/ —— 拆订，恢复各自位置。"""
        try:
            volume = services.unbind_volume(
                volume_id=pk,
                operator=request.data.get("operator", ""))
        except services.RegistrationError as exc:
            return Response({"detail": str(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(BoundVolumeSerializer(volume).data)


class LocateView(APIView):
    """
    GET /api/locate/?serial=<id>&volume=&issue_no=
    或 /api/locate/?serial=<id>&year=&month=

    从任一期号（包括合刊中的任意一期）定位实际位置：
    散置 -> Piece 位置；在订 -> 装订册位置。
    """

    def get(self, request):
        serial_id = request.query_params.get("serial")
        serial = get_object_or_404(Serial, pk=serial_id)
        qs = Issue.objects.filter(serial=serial)
        if all(k in request.query_params for k in ("volume", "issue_no")):
            qs = qs.filter(volume=request.query_params["volume"],
                           issue_no=request.query_params["issue_no"])
        elif all(k in request.query_params for k in ("year", "month")):
            qs = qs.filter(pub_year=request.query_params["year"],
                           pub_month=request.query_params["month"])
        else:
            return Response(
                {"detail": "需要 volume+issue_no 或 year+month 参数"},
                status=status.HTTP_400_BAD_REQUEST)
        issue = qs.first()
        if issue is None:
            return Response(
                {"detail": "没有该期号的发行记录（缺号），"
                           "这不自动等于缺藏"},
                status=status.HTTP_404_NOT_FOUND)
        return Response(services.locate_issue(issue).as_dict())
