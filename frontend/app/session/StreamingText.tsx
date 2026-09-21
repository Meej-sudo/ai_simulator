"use client";

// Words are only ever appended at the tail, so index keys are stable:
// React reuses existing spans and only mounts new tail spans, whose
// CSS mount-animation runs exactly once per new word.
export default function StreamingText({ content }: { content: string }) {
  return (
    <>
      {content.split(/(?<=\s)/).map((word, i) => (
        <span key={i} className="fade-in-token">
          {word}
        </span>
      ))}
    </>
  );
}
