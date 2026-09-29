"""
连续出版物登记的领域模型，分为两层：

1. 书目/发行层（Serial + Issue）
   - Issue 是“有没有发行过这一期”的记录；
   - 发行年月（pub_year/pub_month）与卷期编号（volume/issue_no）分开存；
   - 支持普通期（normal）、两期合刊（combined）、停刊月份（ceased）。
   - 缺号 = 编号序列里没有 Issue 记录，它只是“无发行记录”，
     绝不自动等于“缺藏”。是否缺藏只看实体层有没有 Piece。

2. 实体/馆藏层（Piece + PieceIssue + BoundVolume）
   - Piece 是一个物理实体（一册馆藏），有自己的条码、索取号、位置；
   - 一个合刊 Piece 通过 PieceIssue 显式关联多个 Issue；
   - 绝不允许“用一个条码覆盖多个期号”而没有逐行关联；
   - Piece 可装订入 BoundVolume，位置随册；拆订后恢复各自位置。
"""
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Serial(models.Model):
    """连续出版物（期刊）。"""

    title = models.CharField("刊名", max_length=255)
    issn = models.CharField("ISSN", max_length=9, blank=True, default="")
    publisher = models.CharField("出版者", max_length=255, blank=True,
                                 default="")
    note = models.TextField("备注", blank=True, default="")
    created_at = models.DateTimeField("登记时间", default=timezone.now)

    class Meta:
        verbose_name = "连续出版物"
        verbose_name_plural = verbose_name
        ordering = ("title",)

    def __str__(self):
        return self.title


class Issue(models.Model):
    """
    书目层的期号（发行记录）。

    - normal:   普通期，必须有 volume + issue_no + 发行年月；
    - combined: 合刊中的一期。同一合刊组的多期共用 combined_group，
                入藏时会落进同一个 Piece；
    - ceased:   停刊月份（该刊曾停刊/休刊），无期号，只记录年月。

    卷期编号与发行年月是两组独立字段，以支持跨年卷
    （一卷横跨多个公历年）和提前/延后出版。
    """

    NORMAL = "normal"
    COMBINED = "combined"
    CEASED = "ceased"
    ISSUE_TYPE_CHOICES = [
        (NORMAL, "普通期"),
        (COMBINED, "合刊期"),
        (CEASED, "停刊月份"),
    ]

    serial = models.ForeignKey(
        Serial, on_delete=models.CASCADE,
        related_name="issues", verbose_name="期刊")
    # 编号层
    volume = models.PositiveIntegerField("卷", null=True, blank=True)
    issue_no = models.PositiveIntegerField("期号", null=True, blank=True)
    # 发行时间层（与编号分开录入）
    pub_year = models.PositiveIntegerField("发行年")
    pub_month = models.PositiveIntegerField("发行月", null=True, blank=True)
    # 类型与合刊分组
    issue_type = models.CharField(
        "类型", max_length=10, choices=ISSUE_TYPE_CHOICES, default=NORMAL)
    combined_group = models.CharField(
        "合刊组标识", max_length=40, blank=True, default="",
        help_text="同一合刊组的期入藏到同一实体")
    note = models.CharField("说明", max_length=255, blank=True, default="")
    created_at = models.DateTimeField("登记时间", default=timezone.now)

    class Meta:
        verbose_name = "期号（发行记录）"
        verbose_name_plural = verbose_name
        ordering = ("serial", "volume", "issue_no", "pub_year", "pub_month")
        constraints = [
            # 同一刊同一卷同一期号只能有一条发行记录
            models.UniqueConstraint(
                fields=["serial", "volume", "issue_no"],
                name="uniq_issue_citation",
            ),
            # 同一合刊组标识在一刊内不复用（服务层创建时校验，
            # 两期共用同一标识，故不能在期号行上加唯一约束）
            models.CheckConstraint(
                condition=~Q(issue_type="combined",
                             combined_group=""),
                name="check_combined_has_group",
            ),
            # 卷期编号规则：普通期/合刊期必须有卷、期号；停刊月份必须没有
            models.CheckConstraint(
                condition=(
                    (Q(issue_type__in=["normal", "combined"])
                     & ~Q(volume__isnull=True)
                     & ~Q(issue_no__isnull=True))
                    | (Q(issue_type="ceased")
                       & Q(volume__isnull=True)
                       & Q(issue_no__isnull=True))
                ),
                name="check_issue_numbering_by_type",
            ),
            # 发行月份范围（可空表示只录到年）
            models.CheckConstraint(
                condition=Q(pub_month__isnull=True)
                | Q(pub_month__gte=1, pub_month__lte=12),
                name="check_pub_month_range",
            ),
        ]
        indexes = [
            models.Index(fields=["serial", "volume"]),
            models.Index(fields=["pub_year", "pub_month"]),
        ]

    @property
    def is_combined(self):
        return self.issue_type == self.COMBINED

    @property
    def is_ceased(self):
        return self.issue_type == self.CEASED

    def citation(self):
        """卷期引用，如 第55卷第3期 / 停刊 2024-05。"""
        if self.is_ceased:
            if self.pub_month:
                return f"停刊 {self.pub_year}-{self.pub_month:02d}"
            return f"停刊 {self.pub_year}"
        return f"第{self.volume}卷第{self.issue_no}期"

    def pub_label(self):
        if self.pub_month:
            return f"{self.pub_year}-{self.pub_month:02d}"
        return str(self.pub_year)

    def __str__(self):
        return f"{self.serial.title} {self.citation()}"


class BoundVolume(models.Model):
    """装订册（合订本）：若干 Piece 装订后的馆藏容器。"""

    call_number = models.CharField("合订本索取号", max_length=64,
                                   unique=True)
    barcode = models.CharField("合订本条码", max_length=40, unique=True)
    title_display = models.CharField("册标识", max_length=255,
                                     help_text="如 第55卷合订本(2023-2024)")
    location = models.CharField("馆藏位置", max_length=128)
    bound_at = models.DateTimeField("装订时间", null=True, blank=True)
    is_bound = models.BooleanField("是否在订", default=True)
    note = models.CharField("备注", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "装订册"
        verbose_name_plural = verbose_name
        ordering = ("call_number",)

    def __str__(self):
        return f"{self.call_number} {self.title_display}"


class Piece(models.Model):
    """
    实体层：一个物理分册（一册）。

    普通期：关联 1 个 Issue；合刊：通过 PieceIssue 关联 2+ 个 Issue。
    条码标识实体本身；期号关联全部在 PieceIssue 中显式表达，
    禁止只拿一个条码隐含覆盖多个期号。
    """

    serial = models.ForeignKey(
        Serial, on_delete=models.CASCADE,
        related_name="pieces", verbose_name="期刊")
    barcode = models.CharField("条码", max_length=40, unique=True)
    call_number = models.CharField("索取号", max_length=64)
    # 未装订时的自身位置；装订后位置以 BoundVolume.location 为准
    location = models.CharField("自身位置", max_length=128)
    bound_volume = models.ForeignKey(
        BoundVolume, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pieces", verbose_name="所在装订册")
    # 拆订时恢复位置用
    location_before_binding = models.CharField(
        "装订前位置", max_length=128, blank=True, default="")
    # 装订顺序（册内页码顺序）
    bind_order = models.PositiveIntegerField("装订顺序", default=0)
    issues = models.ManyToManyField(
        Issue, through="PieceIssue",
        related_name="pieces", verbose_name="关联期号")
    created_at = models.DateTimeField("入藏时间", default=timezone.now)

    class Meta:
        verbose_name = "实体分册"
        verbose_name_plural = verbose_name
        ordering = ("serial", "call_number", "bind_order", "barcode")

    @property
    def is_bound(self):
        return self.bound_volume_id is not None

    def effective_location(self):
        """实际位置：在订随册，散置用自身位置。"""
        if self.bound_volume_id and self.bound_volume.is_bound:
            return self.bound_volume.location
        return self.location

    def __str__(self):
        return f"{self.barcode} {self.call_number}"


class PieceIssue(models.Model):
    """
    Piece <-> Issue 的显式关联（含装订后的期号顺序）。

    核心不变量：同一期号最多只能出现在一个 Piece 上（一册在藏）。
    用 PostgreSQL 条件唯一索引保证，而不是由应用层“自觉”。
    """

    piece = models.ForeignKey(
        Piece, on_delete=models.CASCADE,
        related_name="piece_issues", verbose_name="实体分册")
    issue = models.ForeignKey(
        Issue, on_delete=models.CASCADE,
        related_name="piece_issues", verbose_name="期号")
    order = models.PositiveIntegerField("册内顺序", default=0)

    class Meta:
        verbose_name = "实体-期号关联"
        verbose_name_plural = verbose_name
        constraints = [
            # 同一期号只能落在一个实体分册上（一期一册）。
            # 停刊月份不会产生 PieceIssue（入藏服务拒绝 ceased），
            # 因此普通唯一约束即可完整覆盖。
            models.UniqueConstraint(
                fields=["issue"], name="uniq_one_piece_per_issue"),
            models.UniqueConstraint(
                fields=["piece", "issue"], name="uniq_piece_issue_pair"),
        ]
        ordering = ("order", "issue__volume", "issue__issue_no")

    def __str__(self):
        return f"{self.piece.barcode} ↔ {self.issue.citation()}"


class BindingEvent(models.Model):
    """装订/拆订流水，保证拆订后能追溯“曾经在哪一册”。"""

    BIND = "bind"
    UNBIND = "unbind"
    EVENT_CHOICES = [(BIND, "装订"), (UNBIND, "拆订")]

    event_type = models.CharField("操作", max_length=6, choices=EVENT_CHOICES)
    piece = models.ForeignKey(
        Piece, on_delete=models.CASCADE,
        related_name="binding_events", verbose_name="实体分册")
    bound_volume = models.ForeignKey(
        BoundVolume, on_delete=models.SET_NULL, null=True,
        related_name="events", verbose_name="装订册")
    location_from = models.CharField("操作前位置", max_length=128, blank=True)
    location_to = models.CharField("操作后位置", max_length=128, blank=True)
    operator = models.CharField("操作员", max_length=64, blank=True,
                                default="")
    created_at = models.DateTimeField("时间", default=timezone.now)

    class Meta:
        verbose_name = "装订流水"
        verbose_name_plural = verbose_name
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.get_event_type_display()} {self.piece_id} @ {self.created_at:%Y-%m-%d}"
