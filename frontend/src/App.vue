<script setup>
import { onMounted, ref } from 'vue'
import { api } from './api.js'
import Timeline from './components/Timeline.vue'
import IssueRegisterModal from './components/IssueRegisterModal.vue'
import CheckInModal from './components/CheckInModal.vue'
import BindingModal from './components/BindingModal.vue'
import LocateModal from './components/LocateModal.vue'

const serials = ref([])
const currentId = ref(null)
const timeline = ref(null)
const toast = ref('')
const toastErr = ref(false)
const modal = ref('') // issue | checkin | binding | locate | ''
const newTitle = ref('')

function showToast(msg, isErr = false) {
  toast.value = msg
  toastErr.value = isErr
  setTimeout(() => { toast.value = '' }, 3200)
}

async function loadSerials() {
  const data = await api.listSerials()
  serials.value = data.results
  if (!currentId.value && serials.value.length) {
    await selectSerial(serials.value[0].id)
  }
}

async function selectSerial(id) {
  currentId.value = id
  timeline.value = await api.timeline(id)
}

async function refresh() {
  if (currentId.value) timeline.value = await api.timeline(currentId.value)
}

async function createSerial() {
  if (!newTitle.value.trim()) {
    showToast('请输入刊名', true); return
  }
  try {
    const s = await api.createSerial({ title: newTitle.value.trim() })
    newTitle.value = ''
    await loadSerials()
    await selectSerial(s.id)
    showToast('期刊已登记')
  } catch (e) {
    showToast(e.message, true)
  }
}

function closeModal(msg) {
  modal.value = ''
  if (msg) {
    showToast(msg)
    refresh()
  }
}

onMounted(loadSerials)
</script>

<template>
  <header class="app-header">
    <h1>连续出版物登记</h1>
    <span class="sub">
      书目层（期号/发行）与实体层（分册/装订）分离 ·
      缺号 ≠ 缺藏 · 合刊逐期关联
    </span>
  </header>

  <div class="layout">
    <!-- 左：刊名列表 -->
    <aside class="panel">
      <h2>期刊</h2>
      <div
        v-for="s in serials"
        :key="s.id"
        class="serial-item"
        :class="{ active: s.id === currentId }"
        @click="selectSerial(s.id)"
      >
        <div class="t">{{ s.title }}</div>
        <div class="muted">{{ s.issn || '无 ISSN' }}
          · {{ s.issue_count }} 条发行记录</div>
      </div>
      <div style="margin-top: 12px">
        <label>登记新刊</label>
        <input v-model="newTitle" placeholder="刊名"
          @keyup.enter="createSerial" />
        <button style="width: 100%" @click="createSerial">登记期刊</button>
      </div>
    </aside>

    <!-- 右：时间轴 + 操作 -->
    <main class="panel">
      <div class="toolbar">
        <button @click="modal = 'issue'">登记期号/停刊</button>
        <button @click="modal = 'checkin'">期号入藏</button>
        <button @click="modal = 'locate'">定位检索</button>
        <button @click="modal = 'binding'">装订 / 拆订</button>
        <button class="ghost" @click="refresh">刷新时间轴</button>
      </div>

      <Timeline v-if="timeline" :timeline="timeline" />
      <p v-else class="muted">请先在左侧选择或登记一本期刊。</p>
    </main>
  </div>

  <IssueRegisterModal
    v-if="modal === 'issue' && currentId"
    :serial-id="currentId"
    @done="closeModal" @close="modal = ''"
  />
  <CheckInModal
    v-if="modal === 'checkin' && timeline"
    :serial-id="currentId" :timeline="timeline"
    @done="closeModal" @close="modal = ''"
  />
  <BindingModal
    v-if="modal === 'binding' && currentId"
    :serial-id="currentId"
    @done="closeModal" @close="modal = ''"
  />
  <LocateModal
    v-if="modal === 'locate' && currentId"
    :serial-id="currentId"
    @close="modal = ''"
  />

  <transition>
    <div v-if="toast" class="toast" :class="{ err: toastErr }">
      {{ toast }}
    </div>
  </transition>
</template>
