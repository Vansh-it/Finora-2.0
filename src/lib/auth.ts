// Auth storage — keys must stay stable (finora_token, finora_user).
export interface FinoraUser {
  name: string;
  email: string;
}

const TOKEN_KEY = 'finora_token';
const USER_KEY = 'finora_user';
const PENDING_KEY = 'finora_pending_ticker';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): FinoraUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as FinoraUser) : null;
  } catch {
    return null;
  }
}

export function isAuthed(): boolean {
  return Boolean(getToken() && getUser());
}

export function setSession(token: string, user: FinoraUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function setPendingTicker(t: string): void {
  sessionStorage.setItem(PENDING_KEY, t.toUpperCase());
}

export function getPendingTicker(): string | null {
  return sessionStorage.getItem(PENDING_KEY);
}

export function clearPendingTicker(): void {
  sessionStorage.removeItem(PENDING_KEY);
}
