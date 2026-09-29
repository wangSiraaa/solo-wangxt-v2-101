<script setup>
// 装订 / 拆订：
// - 装订只选散置 Piece（同一刊），装订后位置统一为合订本位置，
//   各 Piece 记住自己的原位置；
// - 拆订后每个 Piece 恢复各自位置，期号-实体关联不动。
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({ serialId: Number })
const emit = defineEmits(['done', 'close'])

const tab = ref('bind')
const loose = ref([])
const volumes = ref([])
const selected = ref(new Set())
const busy = ref(false)
const error = ref('')
const form = reactive({
  call_number: '', barcode: '', title_display: '', location: '',
})

async function load() {
  const [lp, bv] = await Promise.all([
    api.listPieces(props.serialId),
    fetch('/api/bound-volumes/?page_size=200')
      .then((r) => r.json()),
  ])
  loose.value = lp.results.filter((p) => !p.is_bound)
  // 只显示含本期刊实体的在订装订册
  volumes.value = bv.results.filter(
    (v) => v.is_bound
      && v.pieces.some((p) => p.serial === props.serialId))
}
onMounted(load)

function toggle(id) {
  const next = new Set(selected.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selected.value = next
}

async function doBind() {
  error.value = ''
  if (!selected.value.size) { error.value = '请选择要装订的实体'; return }
  for (const k of ['call_number', 'barcode', 'title_display', 'location']) {
    if (!form[k]) { error.value = '装订册信息不完整'; return }
  }
  busy.value = true
  try {
    await api.bind({
      piece_ids: [...selected.value],
      call_number: form.call_number,
      barcode: form.barcode,
      title_display: form.title_display,
      location: form.location,
    })
    emit('done',
      `已装订 ${selected.value.size} 个实体为 ${form.call_number}`)
  } catch (e) {
    error.value = e.message
  } finally { busy.value = false }
}

async function doUnbind(v) {
  error.value = ''
  busy.value = true
  try {
    await api.unbind(v.id)
    emit('done',
      `已拆订 ${v.call_number}，各实体恢复装订前位置`)
    await load()
  } catch (e) {
    error.value = e.message
  } finally { busy.value = false }
}

function citeList(p) {
  return p.piece_issues.map((pi) => pi.citation).join('、')
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <h3>装订 / 拆订</h3>
      <div class="tabs">
        <button :class="{ on: tab === 'bind' }"
          @click="tab = 'bind'">装订散置实体</button>
        <button :class="{ on: tab === 'unbind' }"
          @click="tab = 'unbind'">拆订装订册</button>
      </div>

      <div v-if="tab === 'bind'">
        <p class="muted">
          勾选要装订到同一册的散置实体（可包含合刊实体；
          装订后从它覆盖的任一期号都能找到该册）。
        </p>
        <div class="pick-list">
          <label v-for="p in loose" :key="p.id">
            <input type="checkbox"
              :checked="selected.has(p.id)"
              @change="toggle(p.id)" />
            <span>
              {{ p.barcode }} · {{ citeList(p) }}
              <span class="muted">原位置 {{ p.location }}</span>
            </span>
          </label>
          <p v-if="!loose.length" class="muted" style="padding:8px">
            没有可装订的散置实体。
          </p>
        </div>
        <div class="form-grid">
          <div><label>合订本索取号</label>
            <input v-model="form.call_number" /></div>
          <div><label>合订本条码</label>
            <input v-model="form.barcode" /></div>
          <div class="full"><label>册标识</label>
            <input v-model="form.title_display"
              placeholder="如 博览月刊第55卷合订本(2023-2024)" /></div>
          <div class="full"><label>装订后馆藏位置</label>
            <input v-model="form.location" /></div>
        </div>
        <div class="modal-foot">
          <button class="ghost" @click="emit('close')">取消</button>
          <button :disabled="busy" @click="doBind">装订</button>
        </div>
      </div>

      <div v-else>
        <div v-for="v in volumes" :key="v.id" class="result-card">
          <div class="big">{{ v.call_number }} · {{ v.title_display }}</div>
          <div class="muted">位置：{{ v.location }}</div>
          <div class="muted">
            含 {{ v.pieces.length }} 个实体：
            {{ v.pieces.map(p => p.barcode).join('、') }}
          </div>
          <div style="margin-top: 8px">
            <button class="danger" :disabled="busy"
              @click="doUnbind(v)">拆订并恢复各自位置</button>
          </div>
        </div>
        <p v-if="!volumes.length" class="muted">当前没有在订的装订册。</p>
        <div class="modal-foot">
          <button class="ghost" @click="emit('close')">关闭</button>
        </div>
      </div>

      <p v-if="error" style="color: var(--unheld)" class="muted">{{ error }}</p>
    </div>
  </div>
</template>
