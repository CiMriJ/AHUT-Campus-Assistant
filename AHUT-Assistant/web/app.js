const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  data: null,
  viewWeek: 1,
  activeTab: 'home',
  activeDay: new Date().getDay() === 0 ? 7 : new Date().getDay(),
  loggedIn: false,
  captchaStage: 'vpn',
  vpnReady: false,
  username: '',
  studentName: '',
  profile: {},
  gradeQuery: '',
  gradeFilter: 'all',
};

const WEEK_CN = ['', '一', '二', '三', '四', '五', '六', '日'];

/* ---------------- 基础工具 ---------------- */

async function api(path, options = {}) {
  const opts = { headers: { 'Content-Type': 'application/json' }, ...options };
  if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
  const res = await fetch(path, opts);
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error('服务返回异常：' + text.slice(0, 120));
  }
}

let toastTimer = null;
function toast(msg, ms = 2600) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

function loading(on) {
  $('#loading').classList.toggle('hidden', !on);
}

function esc(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ---------------- 本地资料（头像 / 昵称） ---------------- */

function profileKey() {
  return 'ahut.profile.' + (state.username || 'default');
}

function loadProfile() {
  state.profile = {};
  try {
    const raw = localStorage.getItem(profileKey());
    if (raw) {
      const obj = JSON.parse(raw);
      if (obj && typeof obj === 'object') state.profile = obj;
    }
  } catch (e) {
    state.profile = {};
  }
}

function persistProfile() {
  try {
    localStorage.setItem(profileKey(), JSON.stringify(state.profile));
  } catch (e) {
    toast('本地存储空间不足，头像未保存', 4000);
  }
}

function displayName() {
  return (state.profile.nickname || state.studentName || '').trim();
}

function avatarLetter() {
  const nick = (state.profile.nickname || '').trim();
  if (nick) return nick.slice(0, 1);
  if (state.studentName) return state.studentName.slice(-1);
  return '同';
}

function renderAvatar() {
  $$('.js-avatar').forEach((el) => {
    if (state.profile.avatar) {
      el.style.backgroundImage = `url("${state.profile.avatar}")`;
      el.classList.add('has-img');
      el.textContent = '';
    } else {
      el.style.backgroundImage = '';
      el.classList.remove('has-img');
      el.textContent = avatarLetter();
    }
  });
}

function renderAccount() {
  const nameEl = $('#account-name');
  const idEl = $('#account-id');
  if (nameEl) nameEl.textContent = displayName() || '同学';
  if (idEl) idEl.textContent = state.username ? '学号 ' + state.username : '未登录';
}

function openProfile() {
  $('#nickname-input').value = state.profile.nickname || '';
  renderAvatar();
  $('#profile-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeProfile() {
  $('#profile-modal').classList.add('hidden');
  document.body.style.overflow = '';
}

function saveNickname() {
  const value = $('#nickname-input').value.trim().slice(0, 12);
  state.profile.nickname = value;
  persistProfile();
  renderAvatar();
  renderAccount();
  if (state.data) renderHeader(state.data);
  toast(value ? '昵称已保存' : '已恢复默认昵称');
  closeProfile();
}

function pickAvatar() {
  $('#avatar-file').click();
}

function resetAvatar() {
  state.profile.avatar = '';
  persistProfile();
  renderAvatar();
  toast('已恢复默认头像');
}

function handleAvatarFile(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = '';
  if (!file) return;
  if (!/^image\//.test(file.type)) return toast('请选择图片文件');
  if (file.size > 8 * 1024 * 1024) return toast('图片不要超过 8MB');

  const reader = new FileReader();
  reader.onload = () => {
    const img = new Image();
    img.onload = () => {
      const size = 256;
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      const scale = Math.max(size / img.width, size / img.height);
      const w = img.width * scale;
      const h = img.height * scale;
      ctx.drawImage(img, (size - w) / 2, (size - h) / 2, w, h);
      try {
        state.profile.avatar = canvas.toDataURL('image/jpeg', 0.86);
      } catch (err) {
        return toast('头像处理失败，请换一张图片');
      }
      persistProfile();
      renderAvatar();
      toast('头像已更新');
    };
    img.onerror = () => toast('图片读取失败');
    img.src = reader.result;
  };
  reader.onerror = () => toast('图片读取失败');
  reader.readAsDataURL(file);
}

/* ---------------- 登录 ---------------- */

function showLogin() {
  $('#login-view').classList.remove('hidden');
  $('#main-view').classList.add('hidden');
  applyVpnReady();
  refreshCaptcha();
}

function showMain() {
  $('#login-view').classList.add('hidden');
  $('#main-view').classList.remove('hidden');
}

// VPN 已连通时教务系统不需要验证码，直接隐藏验证码输入框
function applyVpnReady() {
  const field = $('#captcha-field');
  if (!field) return;
  field.classList.toggle('hidden', state.vpnReady);
}

function refreshCaptcha() {
  if (state.vpnReady) {
    $('#captcha').value = '';
    return;
  }
  const img = $('#captcha-img');
  img.src = `/api/captcha?stage=${state.captchaStage}&t=` + Date.now();
  img.onerror = () => { img.removeAttribute('src'); img.alt = '点此刷新'; };
  $('#captcha').value = '';
}

let qrTimer = 0;

async function startQr() {
  clearTimeout(qrTimer);
  const panel = $('#qr-panel');
  panel.classList.remove('hidden');
  $('#qr-img').removeAttribute('src');
  $('#qr-tip').textContent = '正在获取二维码…';
  let res;
  try {
    res = await api('/api/qr/start', { method: 'POST', body: {} });
  } catch (e) {
    $('#qr-tip').textContent = '无法连接本地服务';
    return;
  }
  if (!res.ok) {
    $('#qr-tip').textContent = res.error || '二维码获取失败';
    return;
  }
  $('#qr-img').src = res.image;
  $('#qr-tip').textContent = '请用微信「扫一扫」确认登录';
  pollQr();
}

async function pollQr() {
  clearTimeout(qrTimer);
  if ($('#qr-panel').classList.contains('hidden')) return;
  let res;
  try {
    res = await api('/api/qr/poll');
  } catch (e) {
    qrTimer = setTimeout(pollQr, 1500);
    return;
  }
  if (res.state === 'ok') {
    $('#qr-panel').classList.add('hidden');
    toast('登录成功');
    await enterMain(true);
    return;
  }
  if (res.state === 'scanned') {
    $('#qr-tip').textContent = '已扫码，请在手机上点「确认登录」';
  } else if (res.state === 'expired') {
    $('#qr-tip').textContent = '二维码已过期，点下面刷新';
    return;
  } else if (res.state === 'error') {
    $('#qr-tip').textContent = res.error || '扫码登录失败';
    return;
  } else {
    $('#qr-tip').textContent = '等待扫码…';
  }
  qrTimer = setTimeout(pollQr, 800);
}

async function doLogin(e) {
  e.preventDefault();
  const username = $('#username').value.trim();
  const password = $('#password').value;
  const captcha = $('#captcha').value.trim();
  const jwxt_password = $('#jwxt-password').value;
  const remember = $('#remember').checked;

  if (!username || !password) return toast('请输入学号和密码');

  const btn = $('#login-btn');
  btn.disabled = true;
  btn.textContent = '登录中…';
  loading(true);
  try {
    const res = await api('/api/login', {
      method: 'POST',
      body: {
        username, password, captcha, jwxt_password, remember,
        jwxt_captcha: state.captchaStage === 'jwxt' ? captcha : '',
      },
    });
    if (res.ok) {
      $('#login-hint').classList.add('hidden');
      toast('登录成功');
      await enterMain(true);
    } else {
      toast(res.error || '登录失败', 5200);
      state.captchaStage = res.stage === 'jwxt' ? 'jwxt' : 'vpn';
      state.vpnReady = res.stage === 'jwxt' && !res.need_captcha;
      applyVpnReady();
      if (res.need_jwxt_password) {
        $('#jwxt-pwd-wrap').open = true;
        if (res.captcha) $('#jwxt-password').focus();
      }
      refreshCaptcha();
    }
  } catch (err) {
    toast(err.message);
    refreshCaptcha();
  } finally {
    btn.disabled = false;
    btn.textContent = '登 录';
    loading(false);
  }
}

async function leaveAccount(hint) {
  try {
    await api('/api/logout', { method: 'POST' });
  } catch (e) {
    // 本地服务短暂异常也允许回到登录页
  }
  state.data = null;
  state.loggedIn = false;
  state.studentName = '';
  closeProfile();
  switchTab('home');
  const el = $('#login-hint');
  el.textContent = hint;
  el.classList.remove('hidden');
  $('#password').value = '';
  showLogin();
}

/* ---------------- 数据加载 ---------------- */

async function enterMain(force = false) {
  showMain();
  loading(true);
  try {
    const data = await api('/api/dashboard' + (force ? '?refresh=1' : ''));
    if (!data || data.need_login) {
      state.loggedIn = false;
      showLogin();
      toast((data && data.error) || '登录状态已失效，请重新登录');
      return;
    }
    state.loggedIn = true;
    state.data = data;
    const stu = data.student || {};
    const typedUser = $('#username').value.trim();
    if (stu.id) state.username = stu.id;
    else if (typedUser) state.username = typedUser;
    state.studentName = stu.name || '';
    loadProfile();
    state.viewWeek = (data.week && data.week.current) || 1;
    renderAll();
  } catch (err) {
    toast('加载失败：' + err.message);
  } finally {
    loading(false);
  }
}

function renderAll() {
  const d = state.data;
  if (!d) return;
  renderHeader(d);
  renderAccount();
  renderAvatar();
  renderHome(d);
  renderTimetable();
  renderGrades(d);
  renderExams(d);
  renderCalendar(d);
  renderBanner(d);
}

function renderBanner(d) {
  const el = $('#banner');
  const errs = d.errors || {};
  const keys = Object.keys(errs);
  if (d.error) {
    el.textContent = d.error;
    el.className = 'banner';
    return;
  }
  if (keys.length) {
    const map = { timetable: '课程表', grades: '成绩', exams: '考试' };
    el.textContent = '以下模块暂未适配：' + keys.map((k) => map[k] || k).join('、') +
      '。可在「更多 → 导出诊断包」后反馈给开发者。';
    el.className = 'banner info';
    return;
  }
  const tt = d.timetable || {};
  if (tt.adapted === false) {
    el.textContent = '课程表数据解析失败，可能是教务系统页面结构变化，请在「更多」中导出诊断包。';
    el.className = 'banner info';
    return;
  }
  el.className = 'banner hidden';
}

function renderHeader(d) {
  const w = d.week || {};
  const wd = new Date().getDay() === 0 ? 7 : new Date().getDay();
  $('#hello').textContent = `${displayName() || '同学'}，你好`;
  $('#sub-line').textContent = `第 ${w.current} 周${w.estimated ? '（估算）' : ''} · 周${WEEK_CN[wd]}`;
  $('#week-now').textContent = w.current;
  $('#week-total').textContent = w.total;
  const total = Number(w.total) || 20;
  const pct = Math.max(0, Math.min(100, (Number(w.current) || 0) / total * 100));
  $('#week-progress').style.width = pct.toFixed(1) + '%';
}

function periodTime(label) {
  const list = (state.data && state.data.periods) || [];
  return list.find((p) => p.label === label) || null;
}

function isNow(pt) {
  if (!pt || !pt.start || !pt.end) return false;
  const now = new Date();
  const cur = now.getHours() * 60 + now.getMinutes();
  const [sh, sm] = pt.start.split(':').map(Number);
  const [eh, em] = pt.end.split(':').map(Number);
  return cur >= sh * 60 + sm && cur <= eh * 60 + em;
}

function renderHome(d) {
  const week = d.week || {};
  const today = d.today || { courses: [] };
  const courses = today.courses || [];
  $('#today-count').textContent = courses.length;
  $('#gpa').textContent = (d.grade_summary && d.grade_summary.gpa != null) ? d.grade_summary.gpa : '-';

  const now = new Date();
  const todayStr = `${now.getMonth() + 1}月${now.getDate()}日 周${WEEK_CN[now.getDay() === 0 ? 7 : now.getDay()]}`;
  $('#today-date').textContent = todayStr;

  const list = $('#today-list');
  if (!courses.length) {
    list.innerHTML = '<div class="empty">今天没有课，好好休息～</div>';
  } else {
    list.innerHTML = courses.map((c) => {
      const pt = periodTime(c.periodLabel) || periodTime((state.data.periods || [])[Math.max(0, Math.floor((c.period - 1) / 2))]?.label);
      const times = c.start ? `${c.start}-${c.end}` : (pt ? `${pt.start}-${pt.end}` : '');
      const live = c.start ? isNow({ start: c.start, end: c.end }) : isNow(pt);
      return `<div class="tl-item">
        <div class="tl-time">${esc(times || '第' + (c.period || '') + '节')}</div>
        <div class="tl-body ${live ? 'now' : ''}">
          <div class="tl-name">${esc(c.name)}${live ? '<span class="tl-now">进行中</span>' : ''}</div>
          <div class="tl-meta">${esc([c.place, c.teacher].filter(Boolean).join(' · ') || '地点待定')}</div>
        </div>
      </div>`;
    }).join('');
  }

  // 下一节课
  const nextEl = $('#next-course');
  const tagEl = $('#next-tag');
  const all = ((d.timetable || {}).courses || []).filter((c) =>
    !c.weeks || !c.weeks.length || c.weeks.includes(week.current));
  const upcoming = findNext(all, week.current);
  if (!upcoming) {
    nextEl.className = 'next-course empty';
    nextEl.textContent = '近两天没有待上课程';
    tagEl.className = 'tag hidden';
  } else {
    const info = upcoming;
    tagEl.className = 'tag';
    tagEl.textContent = info.today ? '今天' : '明天';
    nextEl.className = 'next-course';
    nextEl.innerHTML = `<div>
        <div class="next-name">${esc(info.course.name)}</div>
        <div class="next-meta">${esc([info.course.place, info.course.teacher].filter(Boolean).join(' · '))}</div>
        <div class="next-meta">${esc(info.label)}</div>
      </div>
      <div class="countdown"><b>${info.diffText}</b><span>${esc(info.countdownLabel)}</span></div>`;
  }

  // 考试
  const exams = (d.exams || []).slice().sort((a, b) => (a.time || '').localeCompare(b.time || ''));
  $('#exam-count').textContent = exams.length ? `共 ${exams.length} 场` : '';
  $('#exam-stat').textContent = exams.filter((e) => {
    const info = parseExamTime(e.time);
    if (!info.date) return true;
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return info.date >= start;
  }).length;

  const mini = $('#exam-mini');
  if (!exams.length) {
    mini.innerHTML = '<div class="empty">暂无考试安排</div>';
  } else {
    mini.innerHTML = exams.slice(0, 4).map((e) => {
      const dtInfo = parseExamTime(e.time);
      return `<div class="exam-chip">
        <div class="d">${esc(dtInfo.short || e.time || '待定')}</div>
        <div class="n">${esc(e.name)}</div>
        <div class="p">${esc([e.place, e.seat ? '座' + e.seat : ''].filter(Boolean).join(' · ') || '地点待定')}</div>
      </div>`;
    }).join('');
  }

  const notices = (d.notices || []).slice(0, 5);
  $('#notice-list').innerHTML = notices.length ? notices.map(noticeHtml).join('')
    : '<div class="empty">暂无通知</div>';
  const full = $('#notice-full');
  if (full) {
    const allNotices = (d.notices || []).slice(0, 12);
    full.innerHTML = allNotices.length ? allNotices.map(noticeHtml).join('') : '<div class="empty">暂无通知</div>';
  }
}

function noticeHtml(n) {
  return `<a class="notice-item" href="${esc(n.url)}" target="_blank" rel="noreferrer">
      <span class="dot"></span>
      <span class="txt">${esc(n.title)}</span>
      <span class="date">${esc((n.date || '').slice(5))}</span>
    </a>`;
}

function findNext(courses, week) {
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const todayIdx = now.getDay() === 0 ? 7 : now.getDay();
  const periods = (state.data && state.data.periods) || [];
  const sorted = courses.slice().sort((a, b) => (a.weekday - b.weekday) || (a.period - b.period));

  for (const offset of [0, 1, 2]) {
    let day = todayIdx + offset;
    if (day > 7) day -= 7;
    const dayCourses = sorted.filter((c) => c.weekday === day);
    for (const c of dayCourses) {
      const pt = periods[Math.min(periods.length - 1, Math.max(0, Math.floor((c.period - 1) / 2)))];
      let startMin = -1;
      let label = '第' + c.period + '节';
      if (pt) {
        const [h, m] = pt.start.split(':').map(Number);
        startMin = h * 60 + m;
        label = `${pt.label} ${pt.start}-${pt.end}`;
      }
      if (offset === 0 && startMin >= 0 && startMin < nowMin) continue;
      let diffText = '';
      let countdownLabel = '';
      if (offset === 0 && startMin >= 0) {
        const diff = startMin - nowMin;
        diffText = diff <= 0 ? '上课中' : `${Math.floor(diff / 60)}:${String(diff % 60).padStart(2, '0')}`;
        countdownLabel = diff <= 0 ? '正在进行' : '后开始';
      } else {
        diffText = offset === 1 ? '明天' : '后天';
        countdownLabel = label;
      }
      return { course: c, today: offset === 0, label, diffText, countdownLabel };
    }
  }
  return null;
}

/* ---------------- 课表 ---------------- */

function courseWeeks(c) {
  return c.weeks && c.weeks.length ? c.weeks.includes(state.viewWeek) : true;
}

function renderTimetable() {
  const d = state.data || {};
  const courses = ((d.timetable || {}).courses || []).filter(courseWeeks);
  const maxWeek = (d.week && d.week.total) || 20;
  $('#view-week').textContent = state.viewWeek;
  $('#week-prev').style.opacity = state.viewWeek <= 1 ? .4 : 1;
  $('#week-next').style.opacity = state.viewWeek >= maxWeek ? .4 : 1;

  const periods = (d.periods || []).map((p, i) => ({ ...p, value: i * 2 + 1 }));
  const grid = $('#tt-grid');
  let html = '<thead><tr><th></th>' + [1, 2, 3, 4, 5, 6, 7].map((i) => `<th>周${WEEK_CN[i]}</th>`).join('') + '</tr></thead><tbody>';
  for (const p of periods) {
    html += `<tr><td class="tt-period">${esc(p.label)}<br/><span style="font-size:10px;opacity:.65">${p.start}</span></td>`;
    for (let day = 1; day <= 7; day++) {
      const cellCourses = courses.filter((c) => c.weekday === day && c.period === p.value);
      if (!cellCourses.length) {
        html += '<td><div class="tt-cell"></div></td>';
      } else {
        html += '<td>' + cellCourses.map((c) =>
          `<div class="tt-cell filled"><b>${esc(c.name)}</b>${esc(c.place || '')}<br/><span style="opacity:.7">${esc(c.teacher || '')}</span></div>`
        ).join('') + '</td>';
      }
    }
    html += '</tr>';
  }
  grid.innerHTML = html + '</tbody>';

  // 移动端按天
  const dayWrap = $('#tt-day');
  let tabs = '<div class="day-tabs">';
  for (let i = 1; i <= 7; i++) {
    tabs += `<button class="day-tab ${state.activeDay === i ? 'active' : ''}" data-day="${i}">周${WEEK_CN[i]}</button>`;
  }
  tabs += '</div>';
  const dayCourses = courses.filter((c) => c.weekday === state.activeDay).sort((a, b) => a.period - b.period);
  const listHtml = dayCourses.length ? dayCourses.map((c, idx) => {
    const pt = (d.periods || [])[Math.max(0, Math.floor((c.period - 1) / 2))];
    return `<div class="course-card c${idx % 6}">
      <div class="cname">${esc(c.name)}</div>
      <div class="cmeta">
        <span><span class="period-badge">${esc(pt ? pt.label : '第' + c.period + '节')}</span>${esc(pt ? pt.start + '-' + pt.end : '')}</span>
        <span>${esc(c.place || '地点待定')}</span>
        <span>${esc(c.teacher || '')}</span>
      </div>
    </div>`;
  }).join('') : '<div class="empty">本周这天没有课</div>';
  dayWrap.innerHTML = tabs + listHtml;
  dayWrap.querySelectorAll('.day-tab').forEach((btn) => {
    btn.onclick = () => { state.activeDay = Number(btn.dataset.day); renderTimetable(); };
  });
}

/* ---------------- 成绩 ---------------- */

function scoreNumber(g) {
  const num = parseFloat(String(g.score).replace(/[^\d.]/g, ''));
  return isNaN(num) ? null : num;
}

function renderGrades(d) {
  const s = d.grade_summary || {};
  $('#g-gpa').textContent = s.gpa != null ? s.gpa : '-';
  $('#g-avg').textContent = s.weighted != null ? s.weighted : '-';
  $('#g-credit').textContent = s.credits != null ? s.credits : '-';
  const items = ((d.grades || {}).items) || [];
  $('#g-count').textContent = items.length ? `${items.length} 门 · 挂科 ${s.failed || 0}` : '';

  const q = state.gradeQuery.toLowerCase();
  const filtered = items.filter((g) => {
    if (q && !String(g.name || '').toLowerCase().includes(q)) return false;
    const num = scoreNumber(g);
    if (state.gradeFilter === 'pass') return num == null || num >= 60;
    if (state.gradeFilter === 'fail') return num != null && num < 60;
    if (state.gradeFilter === 'high') return num != null && num >= 90;
    return true;
  });

  $('#grade-list').innerHTML = filtered.length ? filtered.map((g) => {
    const num = scoreNumber(g);
    const fail = num != null && num < 60;
    const high = num != null && num >= 90;
    return `<div class="grade-item">
      <div class="grade-main">
        <div class="grade-name">${esc(g.name)}</div>
        <div class="grade-sub">${esc([g.nature, g.credit != null ? g.credit + ' 学分' : '', g.term].filter(Boolean).join(' · '))}</div>
      </div>
      <div class="grade-score ${fail ? 'fail' : high ? 'high' : ''}">${esc(g.score || '-')}</div>
      <div class="grade-point">${g.point != null ? g.point + ' 绩点' : ''}</div>
    </div>`;
  }).join('') : `<div class="empty">${items.length ? '没有符合条件的成绩' : '暂无成绩数据'}</div>`;
}

/* ---------------- 考试 ---------------- */

function parseExamTime(text) {
  if (!text) return {};
  const m = String(text).match(/(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})/);
  const t = String(text).match(/(\d{1,2}:\d{2})/);
  if (!m) return { short: text, time: t ? t[1] : '' };
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return {
    short: `${Number(m[2])}月${Number(m[3])}日`,
    date,
    time: t ? t[1] : '',
    month: Number(m[2]),
    day: Number(m[3]),
  };
}

function renderExams(d) {
  const items = (d.exams || []).slice().sort((a, b) => (a.time || '').localeCompare(b.time || ''));
  $('#e-count').textContent = items.length ? `共 ${items.length} 场` : '';
  $('#exam-list').innerHTML = items.length ? items.map((e) => {
    const info = parseExamTime(e.time);
    let days = '';
    if (info.date) {
      const diff = Math.ceil((info.date - new Date(new Date().toDateString())) / 86400000);
      days = diff > 0 ? `${diff} 天后` : diff === 0 ? '今天' : '已结束';
    }
    return `<div class="exam-row">
      <div class="exam-date">
        <div class="m">${info.month ? info.month + '月' : ''}</div>
        <div class="d">${info.day || '—'}</div>
      </div>
      <div class="exam-info">
        <div class="exam-name">${esc(e.name)}</div>
        <div class="exam-meta">
          <span>${esc(e.time || '时间待定')}</span>
          <span>${esc(e.place || '地点待定')}</span>
          ${e.seat ? `<span>座位 ${esc(e.seat)}</span>` : ''}
          ${e.form ? `<span>${esc(e.form)}</span>` : ''}
        </div>
      </div>
      <div class="exam-days">${esc(days)}</div>
    </div>`;
  }).join('') : '<div class="empty">暂无考试安排</div>';
}

/* ---------------- 校历 / 设置 ---------------- */

function renderCalendar(d) {
  const cal = d.calendar || {};
  const items = cal.items || [];
  $('#calendar-list').innerHTML = items.length ? items.map((i) =>
    `<a class="notice-item" href="${esc(i.url)}" target="_blank" rel="noreferrer">
      <span class="dot"></span><span class="txt">${esc(i.title)}</span>
      <span class="date">${esc(i.date || '')}</span>
    </a>`).join('') : '<div class="empty">暂无校历信息</div>';

  const cfgStart = (d.week && d.week.start) || '';
  if (!$('#term-start').value) $('#term-start').value = cfgStart;
  $('#total-weeks').value = (d.week && d.week.total) || 20;
}

/* ---------------- 安装到桌面 ---------------- */

let deferredInstall = null;

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstall = e;
});

window.addEventListener('appinstalled', () => {
  deferredInstall = null;
  const card = $('#install-card');
  if (card) card.classList.add('hidden');
  toast('已安装到桌面');
});

function setupInstallCard() {
  const card = $('#install-card');
  if (!card) return;
  const standalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone
    || /AHUTApp/.test(navigator.userAgent);
  if (standalone) {
    card.classList.add('hidden');
    return;
  }
  const ua = navigator.userAgent;
  const desc = $('#install-desc');
  if (/Android/i.test(ua)) {
    desc.textContent = '添加到桌面后全屏运行。若按钮无效，请点 Chrome 菜单 →「安装应用」或「添加到主屏幕」。';
  } else if (/iPhone|iPad|iPod/i.test(ua)) {
    desc.textContent = '请用 Safari 打开，点底部分享按钮 →「添加到主屏幕」。';
  } else {
    desc.textContent = '把校园助手添加到桌面，像 App 一样全屏打开。也可点地址栏右侧的安装图标。';
  }
  $('#install-btn').addEventListener('click', async () => {
    if (deferredInstall) {
      deferredInstall.prompt();
      try { await deferredInstall.userChoice; } catch (e) { /* 用户取消 */ }
      deferredInstall = null;
      return;
    }
    if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) {
      toast('Safari 底部分享 → 添加到主屏幕', 5000);
    } else {
      toast('浏览器菜单 → 安装应用 / 添加到主屏幕', 5000);
    }
  });
}

/* ---------------- 交互 ---------------- */

function switchTab(tab) {
  state.activeTab = tab;
  $$('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  ['home', 'timetable', 'grades', 'exams', 'more'].forEach((name) => {
    const page = $('#page-' + name);
    if (page) page.classList.toggle('hidden', name !== tab);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function bindEvents() {
  $('#login-form').addEventListener('submit', doLogin);
  $('#captcha-img').addEventListener('click', refreshCaptcha);
  $('#qr-btn').addEventListener('click', startQr);
  $('#qr-refresh').addEventListener('click', startQr);
  $('#refresh-btn').addEventListener('click', () => enterMain(true));

  $$('.tab').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // 个人资料
  $('#avatar-btn').addEventListener('click', openProfile);
  $('#avatar-more').addEventListener('click', openProfile);
  $('#profile-open').addEventListener('click', openProfile);
  $$('[data-close-profile]').forEach((el) => el.addEventListener('click', closeProfile));
  $('#profile-save').addEventListener('click', saveNickname);
  $('#avatar-upload-btn').addEventListener('click', pickAvatar);
  $('#avatar-edit').addEventListener('click', pickAvatar);
  $('#avatar-reset').addEventListener('click', resetAvatar);
  $('#avatar-file').addEventListener('change', handleAvatarFile);
  $('#nickname-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); saveNickname(); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#profile-modal').classList.contains('hidden')) closeProfile();
  });

  // 账号
  $('#switch-account-btn').addEventListener('click', () => {
    const prev = state.username;
    leaveAccount(prev ? `已退出 ${prev}，请输入其他学号登录` : '请输入其他学号登录');
  });
  $('#logout-btn').addEventListener('click', () => {
    if (!window.confirm('确定要退出登录吗？')) return;
    leaveAccount('已退出登录，请重新登录');
  });

  // 成绩筛选
  $('#grade-search').addEventListener('input', (e) => {
    state.gradeQuery = e.target.value.trim();
    if (state.data) renderGrades(state.data);
  });
  $$('#grade-filters .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.gradeFilter = chip.dataset.filter;
      $$('#grade-filters .chip').forEach((c) => c.classList.toggle('active', c === chip));
      if (state.data) renderGrades(state.data);
    });
  });

  $('#week-prev').addEventListener('click', () => {
    if (state.viewWeek > 1) { state.viewWeek -= 1; renderTimetable(); }
  });
  $('#week-next').addEventListener('click', () => {
    const max = (state.data && state.data.week && state.data.week.total) || 20;
    if (state.viewWeek < max) { state.viewWeek += 1; renderTimetable(); }
  });

  $('#save-settings').addEventListener('click', async () => {
    const term_start = $('#term-start').value;
    const total_weeks = Number($('#total-weeks').value) || 20;
    const res = await api('/api/settings', { method: 'POST', body: { term_start, total_weeks } });
    if (res.ok) {
      toast('已保存，正在刷新');
      await enterMain(true);
    } else {
      toast(res.error || '保存失败');
    }
  });

  $('#diag-btn').addEventListener('click', async () => {
    loading(true);
    try {
      const res = await api('/api/diag', { method: 'POST' });
      toast(res.ok ? '诊断包已保存：' + res.dir : (res.error || '导出失败'), 5200);
    } finally {
      loading(false);
    }
  });

  document.addEventListener('click', (e) => {
    const goto = e.target.closest('[data-goto]');
    if (goto) switchTab(goto.dataset.goto);
  });
}

/* ---------------- 启动 ---------------- */

// Android 原生壳：按返回键时先回到首页/关闭弹窗，返回 false 时由系统处理
window.__ahutBack = () => {
  const modal = $('#profile-modal');
  if (modal && !modal.classList.contains('hidden')) {
    closeProfile();
    return true;
  }
  if (state.loggedIn && state.activeTab !== 'home') {
    switchTab('home');
    return true;
  }
  return false;
};

async function boot() {
  bindEvents();
  setupInstallCard();
  try {
    const st = await api('/api/status');
    if (st.username) {
      state.username = st.username;
      $('#username').value = st.username;
    }
    state.vpnReady = !!st.vpn_ready;
    loadProfile();
    renderAvatar();
    renderAccount();
    if (st.logged_in) {
      await enterMain(false);
    } else {
      showLogin();
    }
  } catch (err) {
    showLogin();
    toast('无法连接本地服务：' + err.message);
  }
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
}

boot();
