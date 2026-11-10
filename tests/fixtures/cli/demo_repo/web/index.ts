import { fetchResult } from "./api"

export function main(): Result {
  return fetchResult("/")
}
