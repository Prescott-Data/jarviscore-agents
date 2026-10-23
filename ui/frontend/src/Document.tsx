import ReactMarkdown, { defaultUrlTransform, type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

// A room file is someone's document, not trusted markup: raw HTML in it is
// dropped (never rendered), and links only keep safe protocols.
const components: Components = {
  a: ({ href, title, children }) =>
    <a href={href} title={title} target="_blank" rel="noreferrer noopener">{children}</a>,
  // The Desk only loads its own images; a picture in a document is a link to it.
  img: ({ src, alt }) => typeof src === 'string' && src
    ? <a href={src} target="_blank" rel="noreferrer noopener">{alt || src}</a>
    : <>{alt}</>,
};

export function Document({ text }: { text: string }) {
  return <div className="document">
    <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={defaultUrlTransform} components={components}>
      {text}
    </ReactMarkdown>
  </div>;
}
