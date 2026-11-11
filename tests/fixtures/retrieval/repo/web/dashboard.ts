import { Metric } from "./client"

export interface DashboardOptions {
  compact: boolean
  refreshSeconds: number
}

export class DashboardState {
  private metrics: Metric[] = []

  constructor(private readonly options: DashboardOptions) {}

  update(next: Metric[]): void {
    this.metrics = next.slice()
  }

  summary(): string {
    return `dashboard metrics: ${this.metrics.length}`
  }
}

export function renderDashboard(metrics: Metric[]): string {
  const state = new DashboardState({ compact: true, refreshSeconds: 30 })
  state.update(metrics)
  return state.summary()
}
