import { create } from 'zustand';

interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  setAuth: (token: string, username: string, role: string) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  username: null,
  role: null,
  setAuth: (token, username, role) => set({ token, username, role }),
  clearAuth: () => set({ token: null, username: null, role: null }),
}));
