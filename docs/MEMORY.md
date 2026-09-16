# Memory

Gen-2 does not bypass Gen-1 memory lifecycle. A durable write requires Gen-2 approval, then Gen-1 `memory_write` creates an independently reviewed proposal. Gen-2 persists the waiting state and reconciles real Gen-1 approve/reject decisions after restart without issuing a duplicate write.
