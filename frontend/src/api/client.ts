import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = document.cookie
    .split('; ')
    .find((row) => row.startsWith('token='))
    ?.split('=')[1];
  if (token) {
    config.headers.Authorization = token;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      window.location.href = '/login';
    }
    return Promise.reject(err);
  },
);

export default api;

export const auth = {
  login: (username: string, password: string) =>
    api.post('/login', { username, password }),
  logout: () => api.post('/logout'),
};

export const jobs = {
  list: () => api.get('/jobs'),
  get: (id: string) => api.get(`/jobs/${id}`),
  getLogs: (id: string) => api.get(`/jobs/${id}/logs`),
  uploadUrl: (url: string, shortLength: number, shortsCount: number) =>
    api.post('/upload-url', { url, short_length: shortLength, shorts_count: shortsCount }),
  cleanup: () => api.post('/cleanup'),
};

export const presets = {
  list: () => api.get('/presets/list'),
  save: (name: string, data: object) => api.post('/presets/save', { name, data }),
  load: (name: string) => api.get('/presets/load', { params: { name } }),
};

export const youtube = {
  accounts: () => api.get('/youtube/accounts'),
  authorize: (email: string) => api.post('/youtube/authorize', { email }),
  deleteAccount: (email: string) => api.delete('/youtube/accounts', { data: { email } }),
};
