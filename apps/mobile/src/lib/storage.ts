const prefix = 'hermes.remote.v1:'
export class AccountStorage {
  constructor(
    private account: string,
    private storage: Storage = localStorage
  ) {}
  private key(key: string) {
    return `${prefix}${encodeURIComponent(this.account)}:${key}`
  }
  read<T>(key: string, fallback: T): T {
    const raw = this.storage.getItem(this.key(key))
    if (raw === null) return fallback
    try {
      return JSON.parse(raw) as T
    } catch {
      this.storage.removeItem(this.key(key))
      return fallback
    }
  }
  write(key: string, value: unknown) {
    this.storage.setItem(this.key(key), JSON.stringify(value))
  }
}
export function clearAccountStorage(storage: Storage = localStorage) {
  for (const key of Object.keys(storage)) if (key.startsWith(prefix)) storage.removeItem(key)
}
