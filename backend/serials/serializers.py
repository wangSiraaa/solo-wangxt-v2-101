from rest_framework import serializers

from .models import BoundVolume, Issue, Piece, PieceIssue, Serial


class SerialSerializer(serializers.ModelSerializer):
    issue_count = serializers.IntegerField(source="issues.count",
                                           read_only=True)

    class Meta:
        model = Serial
        fields = ("id", "title", "issn", "publisher", "note",
                  "created_at", "issue_count")


class IssueSerializer(serializers.ModelSerializer):
    """期号（发行记录）。发行年月与卷期编号是分开的字段。"""

    citation = serializers.CharField(read_only=True)
    held = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = ("id", "serial", "volume", "issue_no",
                  "pub_year", "pub_month",
                  "issue_type", "combined_group", "note",
                  "citation", "held", "created_at")

    def get_held(self, obj):
        return PieceIssue.objects.filter(issue=obj).exists()

    def validate(self, attrs):
        itype = attrs.get("issue_type", Issue.NORMAL)
        volume = attrs.get("volume")
        issue_no = attrs.get("issue_no")
        pub_year = attrs.get("pub_year")
        pub_month = attrs.get("pub_month")

        if not pub_year:
            raise serializers.ValidationError({"pub_year": "发行年必填"})
        if pub_month is not None and not (1 <= pub_month <= 12):
            raise serializers.ValidationError(
                {"pub_month": "发行月须在 1-12 之间"})

        if itype == Issue.CEASED:
            if volume is not None or issue_no is not None:
                raise serializers.ValidationError(
                    "停刊月份不填卷、期号")
            if not pub_month:
                raise serializers.ValidationError(
                    {"pub_month": "停刊月份必须录入月份"})
        else:
            if volume is None or issue_no is None:
                raise serializers.ValidationError(
                    "普通期/合刊期必须录入卷和期号")
            if itype == Issue.COMBINED and not attrs.get("combined_group"):
                raise serializers.ValidationError(
                    {"combined_group": "合刊期必须有合刊组标识"})
        return attrs


class CombinedGroupEntrySerializer(serializers.Serializer):
    issue_no = serializers.IntegerField(min_value=1)
    pub_year = serializers.IntegerField()
    pub_month = serializers.IntegerField(min_value=1, max_value=12)


class CombinedGroupCreateSerializer(serializers.Serializer):
    """一次登记一组两期合刊（书目层的两条 Issue）。"""

    serial = serializers.PrimaryKeyRelatedField(queryset=Serial.objects.all())
    volume = serializers.IntegerField(min_value=1)
    group = serializers.CharField(required=False, allow_blank=True)
    entries = CombinedGroupEntrySerializer(many=True, min_length=2)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        nos = [e["issue_no"] for e in attrs["entries"]]
        if len(set(nos)) != len(nos):
            raise serializers.ValidationError("组内期号不能重复")
        return attrs


class PieceIssueSerializer(serializers.ModelSerializer):
    issue_id = serializers.IntegerField(source="issue.id", read_only=True)
    citation = serializers.CharField(source="issue.citation", read_only=True)
    pub_label = serializers.CharField(source="issue.pub_label",
                                      read_only=True)
    issue_type = serializers.CharField(source="issue.issue_type",
                                       read_only=True)

    class Meta:
        model = PieceIssue
        fields = ("issue_id", "citation", "pub_label", "issue_type", "order")


class PieceSerializer(serializers.ModelSerializer):
    piece_issues = PieceIssueSerializer(many=True, read_only=True)
    effective_location = serializers.CharField(read_only=True)
    is_bound = serializers.BooleanField(read_only=True)
    bound_volume_display = serializers.SerializerMethodField()

    class Meta:
        model = Piece
        fields = ("id", "serial", "barcode", "call_number", "location",
                  "bound_volume", "bound_volume_display",
                  "location_before_binding", "bind_order",
                  "is_bound", "effective_location",
                  "piece_issues", "created_at")

    def get_bound_volume_display(self, obj):
        if obj.bound_volume_id:
            bv = obj.bound_volume
            return {"id": bv.id, "call_number": bv.call_number,
                    "title_display": bv.title_display,
                    "location": bv.location, "is_bound": bv.is_bound}
        return None


class CheckInSerializer(serializers.Serializer):
    """入藏：一个实体（条码）显式关联一个或多个期号。"""

    serial = serializers.PrimaryKeyRelatedField(queryset=Serial.objects.all())
    issue_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False)
    barcode = serializers.CharField(max_length=40)
    call_number = serializers.CharField(max_length=64)
    location = serializers.CharField(max_length=128)


class BoundVolumeSerializer(serializers.ModelSerializer):
    pieces = PieceSerializer(many=True, read_only=True)

    class Meta:
        model = BoundVolume
        fields = ("id", "call_number", "barcode", "title_display",
                  "location", "bound_at", "is_bound", "note", "pieces")


class BindSerializer(serializers.Serializer):
    piece_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False)
    call_number = serializers.CharField(max_length=64)
    barcode = serializers.CharField(max_length=40)
    title_display = serializers.CharField(max_length=255)
    location = serializers.CharField(max_length=128)
    operator = serializers.CharField(required=False, allow_blank=True)
