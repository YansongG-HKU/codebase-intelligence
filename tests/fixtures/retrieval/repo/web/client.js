export interface Metric {
  name: string
  value: number
}

export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  async fetchMetrics(endpoint: string): Promise<Metric[]> {
    const response = await fetch(`${this.baseUrl}${endpoint}`)
    return response.json()
  }
}

export async function loadDashboardMetrics(endpoint: string): Promise<Metric[]> {
  const client = new ApiClient("https://metrics.example")
  return client.fetchMetrics(endpoint)
}
