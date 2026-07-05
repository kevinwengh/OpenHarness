import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function safeUrl(url: string) {
  const normalized = url.trim();
  if (!normalized || normalized.startsWith("//")) return "";
  const scheme = normalized.match(/^([a-z][a-z0-9+.-]*):/i)?.[1]?.toLowerCase();
  if (!scheme) return normalized;
  return scheme === "http" || scheme === "https" || scheme === "mailto" ? normalized : "";
}

export function SafeMarkdown({ children, compact = false }: { children: string; compact?: boolean }) {
  return (
    <div className={compact ? "markdown markdown--compact" : "markdown"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={safeUrl}
        components={{
          a: ({ href, children: linkChildren, ...props }) => {
            if (!href) return <span className="markdown-unsafe-link">{linkChildren}</span>;
            const external = Boolean(href?.startsWith("http://") || href?.startsWith("https://"));
            return <a {...props} href={href} target={external ? "_blank" : undefined} rel={external ? "noopener noreferrer" : undefined}>{linkChildren}</a>;
          },
          img: ({ alt }) => <span className="markdown-image-note">[Image omitted{alt ? `: ${alt}` : ""}]</span>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
