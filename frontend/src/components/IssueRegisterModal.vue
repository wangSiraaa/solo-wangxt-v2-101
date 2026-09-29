<script setup>
// 登记期号（书目/发行层）。发行年月与卷期编号分两组字段录入。
import { reactive, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({ serialId: Number })
const emit = defineEmits(['done', 'close'])

const tab = ref('normal') // normal | combined | ceased
const error = ref('')
const busy = ref(false)

const normal = reactive({
  volume: '', issue_no: '',
  pub_year: new Date().getFullYear(), pub_month: '',
  note: '',
})
const ceased = reactive({ pub_year: new Date().getFullYear(),
  pub_month: '', note: '' })
const combined = reactive({
  volume: '',
  a_no: '', a_year: new Date().getFullYear(), a_month: '',
  b_no: '', b_year: new Date().getFullYear(), b_month: '',
  note: '',
})

async function submitNormal() {
  error.value = ''
  busy.value = true
  try {
    await api.createIssue({
      serial: props.serialId,
      issue_type: 'normal',
      volume: Number(normal.volume),
      issue_no: Number(normal.issue_no),
      pub_year: Number(normal.pub_year),
      pub_month: normal.pub_month ? Number(normal.pub_month) : null,
      note: normal.note,
    })
    emit('done', '普通期已登记')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}

async function submitCeased() {
  error.value = ''
  busy.value = true
  try {
    await api.createIssue({
      serial: props.serialId,
      issue_type: 'ceased',
      volume: null, issue_no: null,
      pub_year: Number(ceased.pub_year),
      pub_month: Number(ceased.pub_month),
      note: ceased.note,
    })
    emit('done', '停刊月份已登记（不占卷期编号）')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}

async function submitCombined() {
  error.value = ''
  busy.value = true
  try {
    await api.createCombinedGroup({
      serial: props.serialId,
      volume: Number(combined.volume),
      entries: [
        { issue_no: Number(combined.a_no),
          pub_year: Number(combined.a_year),
          pub_month: Number(combined.a_month) },
        { issue_no: Number(combined.b_no),
          pub_year: Number(combined.b_year),
          pub_month: Number(combined.b_month) },
      ],
      note: combined.note,
    })
    emit('done', '两期合刊已登记：入藏时必须整组关联到同一实体')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <h3>登记发行记录（书目层）</h3>
      <div class="tabs">
        <button :class="{ on: tab === 'normal' }"
          @click="tab = 'normal'">普通期</button>
        <button :class="{ on: tab === 'combined' }"
          @click="tab = 'combined'">两期合刊</button>
        <button :class="{ on: tab === 'ceased' }"
          @click="tab = 'ceased'">停刊月份</button>
      </div>

      <div v-if="tab === 'normal'">
        <div class="form-grid">
          <div><label>卷（编号层）</label><input v-model="normal.volume"
            type="number" min="1" /></div>
          <div><label>期号（编号层）</label><input v-model="normal.issue_no"
            type="number" min="1" /></div>
          <div><label>发行年（时间层）</label><input v-model="normal.pub_year"
            type="number" /></div>
          <div><label>发行月（可空）</label><input v-model="normal.pub_month"
            type="number" min="1" max="12" placeholder="只录到年可留空" /></div>
          <div class="full"><label>说明</label>
            <input v-model="normal.note" /></div>
        </div>
        <p class="muted">卷期编号与发行年月分开录入，支持跨年卷。</p>
        <div class="modal-foot">
          <button class="ghost" @click="emit('close')">取消</button>
          <button :disabled="busy" @click="submitNormal">登记</button>
        </div>
      </div>

      <div v-else-if="tab === 'ceased'">
        <div class="form-grid">
          <div><label>停刊年</label><input v-model="ceased.pub_year"
            type="number" /></div>
          <div><label>停刊月</label><input v-model="ceased.pub_month"
            type="number" min="1" max="12" /></div>
          <div class="full"><label>原因/说明</label>
            <input v-model="ceased.note" placeholder="如 暑期休刊" /></div>
        </div>
        <p class="muted">停刊月份不占卷、期号，也不会产生馆藏实体。</p>
        <div class="modal-foot">
          <button class="ghost" @click="emit('close')">取消</button>
          <button :disabled="busy" @click="submitCeased">登记停刊</button>
        </div>
      </div>

      <div v-else>
        <div class="form-grid">
          <div class="full"><label>卷</label>
            <input v-model="combined.volume" type="number" min="1" /></div>
        </div>
        <p class="muted" style="margin:6px 0">合刊第一期</p>
        <div class="form-grid">
          <div><label>期号</label><input v-model="combined.a_no"
            type="number" min="1" /></div>
          <div><label>发行月</label><input v-model="combined.a_month"
            type="number" min="1" max="12" /></div>
          <div class="full"><label>发行年</label>
            <input v-model="combined.a_year" type="number" /></div>
        </div>
        <p class="muted" style="margin:6px 0">合刊第二期</p>
        <div class="form-grid">
          <div><label>期号</label><input v-model="combined.b_no"
            type="number" min="1" /></div>
          <div><label>发行月</label><input v-model="combined.b_month"
            type="number" min="1" max="12" /></div>
          <div class="full"><label>发行年</label>
            <input v-model="combined.b_year" type="number" /></div>
          <div class="full"><label>说明</label>
            <input v-model="combined.note" /></div>
        </div>
        <p class="muted">
          两条期号记录会被标为同一合刊组；入藏时系统逐行关联，
          不允许只拿一个条码“盖住”两个期号。
        </p>
        <div class="modal-foot">
          <button class="ghost" @click="emit('close')">取消</button>
          <button :disabled="busy" @click="submitCombined">登记合刊</button>
        </div>
      </div>

      <p v-if="error" class="muted"
        style="color: var(--unheld); margin-top: 10px">{{ error }}</p>
    </div>
  </div>
</template>
