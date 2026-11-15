'use strict';
const form = document.querySelector('#login-form');
const password = document.querySelector('#password');
const toggle = document.querySelector('#toggle-password');
const error = document.querySelector('#login-error');
const submit = document.querySelector('#login-submit');
toggle.addEventListener('click', () => {
  const visible = password.type === 'password';
  password.type = visible ? 'text' : 'password';
  toggle.setAttribute('aria-pressed', String(visible));
  toggle.setAttribute('aria-label', visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submit.disabled) return;
  error.hidden = true;
  submit.disabled = true;
  submit.querySelector('span').textContent = 'Đang đăng nhập…';
  try {
    const response = await fetch('/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: document.querySelector('#username').value.trim(), password: password.value,
        next: new URLSearchParams(location.search).get('next') || '/'})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Chưa đăng nhập được. Vui lòng thử lại.');
    location.replace(result.next);
  } catch (cause) {
    error.textContent = cause instanceof TypeError ? 'Không kết nối được với máy chủ. Vui lòng thử lại.' : cause.message;
    error.hidden = false;
    password.focus();
  } finally {
    submit.disabled = false;
    submit.querySelector('span').textContent = 'Đăng nhập';
  }
});
