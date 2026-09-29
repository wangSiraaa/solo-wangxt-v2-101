from django.contrib import admin

from .models import (
    BindingEvent, BoundVolume, Issue, Piece, PieceIssue, Serial,
)

admin.site.register(Serial)
admin.site.register(Issue)
admin.site.register(Piece)
admin.site.register(PieceIssue)
admin.site.register(BoundVolume)
admin.site.register(BindingEvent)
