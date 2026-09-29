<script setup>
// 馆员时间轴：按卷展示“期号覆盖”和“实际位置”。
// 缺号（无发行记录）用空槽位表达，绝不与缺藏（有发行记录但无实体）混用。
import { computed } from 'vue'

const props = defineProps({
  timeline: { type: Object, required: true },
})
defineEmits(['refresh'])

// 每卷需要渲染 1..最大期号，缺号补空槽
function cellsWithGaps(v) {
  const maxNo = v.cells.length
    ? Math.max(...v.cells.map((c) => c.issue_no))
    : 0
  const byNo = new Map(v.cells.map((c) => [c.issue_no, c]))
  const out = []
  for (let no = 1; no <= maxNo; no++) {
    out.push({ no, cell: byNo.get(no) || null })
  }
  return out
}

const rows = computed(() =>
  props.timeline.volumes.map((v) => ({ v, slots: cellsWithGaps(v) })),
)

function cellTitle(c) {
  if (!c.held) return `${c.citation}：有发行记录但当前无实体（缺藏）`
  const lines = [c.citation, c.pub_label]
  if (c.bound_volume) {
    lines.push(`装订于 ${c.bound_volume.call_number}`,
      c.bound_volume.location)
  }
  if (c.issue_type === 'combined') {
    lines.push(`合刊，同实体另含第 ${c.combined_with.join('、')} 期`)
  }
  return lines.join('\n')
}
</script>

<template>
  <div>
    <div v-for="{ v, slots } in rows" :key="v.volume" class="volume-block">
      <div class="volume-head">
        <span class="badge">第{{ v.volume }}卷</span>
        <span v-if="v.is_cross_year" class="crossyear">
          跨年卷 · {{ v.pub_years.join(' / ') }}
        </span>
        <span v-else class="muted">{{ v.pub_years.join(' / ') }} 年</span>
        <span v-if="v.numbering_gaps.length" class="muted">
          缺号（无发行记录）：第 {{ v.numbering_gaps.join('、') }} 期
        </span>
        <span
          v-if="v.unheld.length"
          class="muted"
          style="color: var(--unheld)"
        >
          缺藏（有发行记录无实体）：{{ v.unheld.join('、') }}
        </span>
      </div>

      <div class="track">
        <template v-for="{ no, cell } in slots" :key="no">
          <div
            v-if="cell"
            class="cell"
            :class="{
              held: cell.held && !cell.bound,
              bound: cell.bound,
              combined: cell.issue_type === 'combined',
              unheld: !cell.held,
            }"
            :title="cellTitle(cell)"
          >
            <div class="no">第{{ no }}期</div>
            <div class="date">{{ cell.pub_label }}</div>
            <div class="state">
              <template v-if="cell.bound">在订</template>
              <template v-else-if="cell.held">在藏 · 散置</template>
              <template v-else>缺藏（无实体）</template>
            </div>
            <div v-if="cell.piece" class="barcode">
              {{ cell.piece.barcode }}
            </div>
            <div class="loc">📍 {{ cell.location || '—' }}</div>
          </div>
          <div
            v-else
            class="gap-cell"
            title="只有“没有发行记录”这一含义，不自动等于缺藏"
          >
            第{{ no }}期<br />缺号
          </div>
        </template>
      </div>

      <div v-if="v.month_gaps.length" class="muted" style="margin-top: 6px">
        月份无发行记录：{{ v.month_gaps.join('、') }}
      </div>
    </div>

    <div v-if="timeline.ceased_months.length" class="ceased-row">
      <strong class="muted" style="font-size: 12px; align-self: center">
        停刊月份：
      </strong>
      <span
        v-for="c in timeline.ceased_months"
        :key="c.id"
        class="ceased-chip"
        :title="c.note"
      >
        ✋ {{ c.label }}<template v-if="c.note">（{{ c.note }}）</template>
      </span>
    </div>

    <div class="legend">
      <span class="l-held">在藏散置（有实体）</span>
      <span class="l-bound">已装订（位置随合订本）</span>
      <span class="l-unheld">缺藏：有发行记录但无实体</span>
      <span class="l-gap">缺号：无发行记录，不等于缺藏</span>
      <span class="l-ceased">停刊月份（不出版）</span>
    </div>
  </div>
</template>
