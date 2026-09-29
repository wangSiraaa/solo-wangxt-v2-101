// REST API 封装：所有期号-实体关系都走显式 issue_ids
const BASE = '/api'

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof data === 'string' ? data
      : data.detail || JSON.stringify(data)
    throw new Error(detail)
  }
  return data
}

export const api = {
  listSerials: () => request('/serials/'),
  createSerial: (b) => request('/serials/', { method: 'POST', body: b }),
  timeline: (id) => request(`/serials/${id}/timeline/`),

  createIssue: (b) => request('/issues/', { method: 'POST', body: b }),
  createCombinedGroup: (b) =>
    request('/serials/combined_group/', { method: 'POST', body: b }),

  checkIn: (serialId, b) =>
    request(`/serials/${serialId}/check_in/`, { method: 'POST', body: b }),
  listPieces: (serialId) =>
    request(`/pieces/?serial=${serialId}&page_size=200`),

  bind: (b) => request('/bound-volumes/bind/', {
    method: 'POST', body: b,
  }),
  unbind: (id) => request(`/bound-volumes/${id}/unbind/`, {
    method: 'POST', body: {},
  }),

  locateByCitation: (serial, volume, issueNo) =>
    request(`/locate/?serial=${serial}&volume=${volume}` +
      `&issue_no=${issueNo}`),
  locateByMonth: (serial, year, month) =>
    request(`/locate/?serial=${serial}&year=${year}&month=${month}`),
  locateRaw: async (url) => {
    const res = await fetch(BASE + url)
    const data = await res.json()
    return { ok: res.ok, status: res.status, data }
  },
}
