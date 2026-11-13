import { useEffect, useState } from "react";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  if (!open) return null;

  return (
    <div className="cmd-palette-overlay" onClick={() => setOpen(false)}>
      <div className="cmd-palette" onClick={(e) => e.stopPropagation()}>
        <input
          autoFocus
          placeholder="Search cases, evidence, or commands..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <ul>
          <li>⌘ Go to Cases</li>
          <li>⌘ Go to War Room</li>
          <li>⌘ New Case</li>
        </ul>
      </div>
    </div>
  );
}
