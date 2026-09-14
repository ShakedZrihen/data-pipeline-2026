import { getStore } from './client'
import type { Branch } from './types'

/**
 * Chains are not consistent about padding branch ids: Shufersal's Stores file
 * publishes `1`..`98` while its price files say `001`, and the two are joined
 * by string equality, so 415 branches resolve to nothing. Dropping leading
 * zeros on both sides bridges that.
 *
 * This belongs in the stores service, which should persist one canonical form.
 * It lives here so the UI shows branch names today, and it is deliberately
 * narrow: nothing else about the id is rewritten.
 */
function canonicalId(storeId: string): string {
  const trimmed = storeId.trim()
  const unpadded = trimmed.replace(/^0+(?=\d)/, '')
  return unpadded === '' ? trimmed : unpadded
}

export interface BranchIndex {
  find(storeId: string): Branch | undefined
}

function buildIndex(branches: Branch[]): BranchIndex {
  const exact = new Map<string, Branch>()
  const canonical = new Map<string, Branch>()

  for (const branch of branches) {
    exact.set(branch.branch_id, branch)
    const key = canonicalId(branch.branch_id)
    // First writer wins, so a chain that really distinguishes `1` from `001`
    // still resolves each of them through the exact map below.
    if (!canonical.has(key)) canonical.set(key, branch)
  }

  return {
    find: (storeId) => exact.get(storeId) ?? canonical.get(canonicalId(storeId)),
  }
}

// Price rows carry a bare `store_id`, and the only endpoint that names it is
// /stores/{chain_id}, which returns every branch of that chain at once. So the
// whole chain is fetched once and kept for the session.
const byChain = new Map<string, Promise<BranchIndex>>()

export function loadBranches(chainId: string): Promise<BranchIndex> {
  let pending = byChain.get(chainId)
  if (!pending) {
    pending = getStore(chainId)
      .then((store) => buildIndex(store.branches))
      // A chain can publish prices with no rows in `branches` yet, so a 404
      // here is expected and must not blank the table.
      .catch(() => buildIndex([]))
    byChain.set(chainId, pending)
  }
  return pending
}

export function describeBranch(branch: Branch | undefined, storeId: string): string {
  if (!branch) return `סניף ${storeId}`
  const parts = [branch.name?.trim(), branch.city?.trim()].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : `סניף ${storeId}`
}
