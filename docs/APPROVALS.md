# Approvals

Approvals are persistent objects with PENDING, APPROVED, REJECTED, EXPIRED and CANCELLED states. Pending work never executes. Gen-2 approvals survive restart; Gen-1 memory-review approvals are separately reconciled after restart. Rejected or cancelled approvals prevent execution.
