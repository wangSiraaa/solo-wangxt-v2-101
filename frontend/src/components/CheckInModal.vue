<script setup>
// 入藏：把“期号（书目层）”落成“实体 Piece（馆藏层）”。
// 一个条码可以关联多个期号（合刊），但每个期号都是显式勾选的一行，
// 合刊必须整组入藏；已有实体的期号不可再次入藏。
import { computed, reactive, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  serialId: Number,
  timeline: Object,
})
const emit = defineEmits(['done', 'close'])

const error = ref('')
const busy = ref(false)
const selected = ref(new Set())
const form = reactive({
  barcode: '', call_number: '', location: '',
})

// 可入藏：普通期/合刊期，且当前没有实体
const candidates = computed(() =>
  props.timeline.volumes
    .flatMap((v) => v.cells)
    .filter((c) => !c.held)
    .sort((a, b) =>
      a.volume - b.volume || a.issue_no - b.issue_no),
)

// 同合刊组联动勾选，保证整组
function toggle(cell) {
  const next = new Set(selected.value)
  const group = cell.combined_group
  const mates = group
    ? candidates.value.filter((c) => c.combined_group === group)
    : [cell]
  const anyOn = mates.some((m) => next.has(m.issue_id))
  if (anyOn) mates.forEach((m) => next.delete(m.issue_id))
  else mates.forEach((m) => next.add(m.issue_id))
  selected.value = next
}

async function submit() {
  error.value = ''
  if (!selected.value.size) {
    error.value = '请至少选择一个期号'
    return
  }
  if (!form.barcode || !form.call_number || !form.location) {
    error.value = '条码、索取号、位置都必填'
    return
  }
  busy.value = true
  try {
    const piece = await api.checkIn(props.serialId, {
      issue_ids: [...selected.value],
      barcode: form.barcode,
      call_number: form.call_number,
      location: form.location,
    })
    const n = piece.piece_issues.length
    emit('done', `已入藏实体 ${form.barcode}，显式关联 ${n} 个期号`)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <h3>期号入藏（实体层）</h3>
      <p class="muted">
        勾选要落到<strong>同一个物理实体</strong>的期号。普通期选 1 个；
        两期合刊会自动整组勾选 —— 每个期号都是显式关联行，
        装订后也能从任一期号找到该册。
      </p>
      <div class="pick-list">
        <label
          v-for="c in candidates"
          :key="c.issue_id"
        >
          <input
            type="checkbox"
            :checked="selected.has(c.issue_id)"
            @change="toggle(c)"
          />
          <span>
            {{ c.citation }}
            <span class="muted">{{ c.pub_label }}</span>
            <em v-if="c.issue_type === 'combined'"
              class="tag bound">合刊</em>
          </span>
        </label>
        <p v-if="!candidates.length" class="muted"
          style="padding: 8px">没有待入藏的期号（停刊月份不入藏）。</p>
      </div>
      <div class="form-grid">
        <div><label>实体条码</label><input v-model="form.barcode"
          placeholder="如 BC-55-78" /></div>
        <div><label>索取号</label><input v-model="form.call_number"
          placeholder="如 Q/BL/55/7-8" /></div>
        <div class="full"><label>散置位置（装订前位置）</label>
          <input v-model="form.location" placeholder="如 现刊架-A12" /></div>
      </div>
      <p v-if="error" style="color: var(--unheld)" class="muted">{{ error }}</p>
      <div class="modal-foot">
        <button class="ghost" @click="emit('close')">取消</button>
        <button :disabled="busy" @click="submit">入藏</button>
      </div>
    </div>
  </div>
</template>
