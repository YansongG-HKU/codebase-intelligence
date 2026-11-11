package worker

// Job is one queued unit of work.
type Job struct {
	ID      string
	Payload string
}

// ProcessJobs drains the queue in deterministic order.
func ProcessJobs(jobs []Job) int {
	processed := 0
	for _, job := range jobs {
		if job.ID == "" {
			continue
		}
		processed++
	}
	return processed
}

// QueueHealth reports whether the worker queue is empty.
func QueueHealth(jobs []Job) bool {
	return len(jobs) == 0
}
