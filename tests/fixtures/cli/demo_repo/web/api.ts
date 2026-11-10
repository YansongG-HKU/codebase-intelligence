export interface Result {
  ok: boolean
}

export function fetchResult(path: string): Result {
  return { ok: path.length > 0 }
}
