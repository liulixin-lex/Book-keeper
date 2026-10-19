/** Global 记一笔: one sheet reachable from every screen (sidebar capsule, N key, the phone's raised ＋). */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Sheet } from "@/components/ui";
import { useUndoToast } from "@/components/toast";
import { EntryForm, type EntryPrefill, type EntryResult } from "./EntryForm";

interface EntryApi {
  open: (prefill?: EntryPrefill) => void;
}

const EntryContext = createContext<EntryApi>({ open: () => {} });

export function EntryProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ open: boolean; prefill?: EntryPrefill; key: number }>({ open: false, key: 0 });
  const undoToast = useUndoToast();
  const open = useCallback((prefill?: EntryPrefill) => setState((s) => ({ open: true, prefill, key: s.key + 1 })), []);
  const api = useMemo(() => ({ open }), [open]);

  function done({ txn, changeSet }: EntryResult) {
    setState((s) => ({ ...s, open: false }));
    undoToast(`已记一笔 · ${txn.description}`, changeSet, `已撤销 ${txn.number}`);
  }

  return (
    <EntryContext.Provider value={api}>
      {children}
      <Sheet open={state.open} onClose={() => setState((s) => ({ ...s, open: false }))} title="记一笔" width={520}>
        <EntryForm key={state.key} prefill={state.prefill} onDone={done} />
      </Sheet>
    </EntryContext.Provider>
  );
}

export function useEntry(): EntryApi {
  return useContext(EntryContext);
}
