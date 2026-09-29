<script setup>
// 定位检索：两条独立路径（卷期编号 / 发行年月），
// 明确区分“缺号（无发行记录）”“缺藏（有发行无实体）”“在藏/在订”。
import { reactive, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({ serialId: Number })
const emit = defineEmits(['close'])

const mode = ref('citation')
const form = reactive({
  volume: '', issue_no: '', year: '', month: '',
})
const result = ref(null) // {ok,status,data}
const error = ref('')

async function search() {
  error.value = ''
  result.value = null
  try {
    let url
    if (mode.value === 'citation') {
      if (!form.volume || !form.issue_no) {
        error.value = '请输入卷和期号'; return
      }
      url = `/locate/?serial=${props.serialId}` +
        `&volume=${form.volume}&issue_no=${form.issue_no}`
    } else {
      if (!form.year || !form.month) {
        error.value = '请输入发行年和月'; return
      }
      url = `/locate/?serial=${props.serialId}` +
        `&year=${form.year}&month=${form.month}`
    }
    result.value = await api.locateRaw(url)
  } catch (e) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal">
      <h3>按期号定位实体</h3>
      <div class="tabs">
        <button :class="{ on: mode === 'citation' }"
          @click="mode = 'citation'; result = null">按卷期编号</button>
        <button :class="{ on: mode === 'month' }"
          @click="mode = 'month'; result = null">按发行年月</button>
      </div>

      <div class="searchbar">
        <template v-if="mode === 'citation'">
          <input v-model="form.volume" type="number" placeholder="卷" />
          <input v-model="form.issue_no" type="number" placeholder="期号" />
        </template>
        <template v-else>
          <input v-model="form.year" type="number" placeholder="发行年" />
          <input v-model="form.month" type="number" min="1" max="12"
            placeholder="发行月" />
        </template>
        <button @click="search">检索</button>
      </div>

      <p v-if="error" style="color: var(--unheld)" class="muted">{{ error }}</p>

      <div v-if="result && !result.ok" class="result-card">
        <div class="big">缺号
          <span class="tag none">无发行记录</span>
        </div>
        <div class="muted">{{ result.data.detail }}</div>
      </div>

      <div v-else-if="result" class="result-card">
        <div class="big">
          {{ result.data.issue.citation }}
          <span class="muted">（{{ result.data.issue.pub_label }}）</span>
          <span v-if="result.data.location_kind === 'bound'"
            class="tag bound">在订</span>
          <span v-else-if="result.data.location_kind === 'piece'"
            class="tag held">在藏散置</span>
          <span v-else-if="result.data.location_kind === 'not_held'"
            class="tag none">缺藏</span>
          <span v-else class="tag ceased">停刊</span>
        </div>

        <div>📍 实际位置：{{ result.data.location }}</div>

        <template v-if="result.data.piece">
          <hr style="border:0;border-top:1px solid var(--line);margin:10px 0" />
          <div>实体条码：{{ result.data.piece.barcode }}</div>
          <div>索取号：{{ result.data.piece.call_number }}</div>
          <div>
            该实体覆盖：
            <strong>{{ result.data.piece.covers_citations.join('、') }}</strong>
            <span class="muted">（合刊多期为逐行显式关联）</span>
          </div>
        </template>
        <div v-if="result.data.bound_volume"
          style="margin-top: 8px; color: var(--bound)">
          📚 装订册：{{ result.data.bound_volume.call_number }}
          （{{ result.data.bound_volume.title_display }}）
        </div>
      </div>

      <div class="modal-foot">
        <button class="ghost" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>
