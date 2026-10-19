import { createContext, useContext } from "react";

/** The book every screen works in. Chosen once at sign-in (or from the switcher) and remembered per browser. */
export const BookContext = createContext<string | null>(null);

const STORAGE_KEY = "bk.book";

export function useBookId(): string {
  const id = useContext(BookContext);
  if (!id) throw new Error("useBookId outside <BookContext>");
  return id;
}

export function rememberedBook(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function rememberBook(id: string): void {
  localStorage.setItem(STORAGE_KEY, id);
}
