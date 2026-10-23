import { useState, type ComponentType } from 'react';
import {
  Archive, ExternalLink, Eye, File, FileImage, FileText, FileType2,
  Mail, Music2, Presentation, Sheet, Video, X,
} from 'lucide-react';
import { artifactSchema, type Artifact, type RunEvent } from './api';
import { Markdown } from './Markdown';

const icons: Record<Artifact['artifact_type'], ComponentType<{ size?: number }>> = {
  document: FileText,
  presentation: Presentation,
  spreadsheet: Sheet,
  pdf: FileType2,
  email: Mail,
  image: FileImage,
  audio: Music2,
  video: Video,
  archive: Archive,
  file: File,
};

const labels: Record<Artifact['artifact_type'], string> = {
  document: 'Document', presentation: 'Presentation', spreadsheet: 'Spreadsheet',
  pdf: 'PDF', email: 'Email', image: 'Image', audio: 'Audio', video: 'Video',
  archive: 'Archive', file: 'File',
};

function Preview({ artifact }: { artifact: Artifact }) {
  if (artifact.preview?.kind === 'image' && artifact.preview.url) {
    return <img className="artifact-media" src={artifact.preview.url} alt={artifact.title} referrerPolicy="no-referrer" />;
  }
  if (artifact.preview?.kind === 'pdf' && artifact.preview.url) {
    return <iframe className="artifact-pdf" src={artifact.preview.url} title={`Preview ${artifact.title}`} sandbox="allow-same-origin" referrerPolicy="no-referrer" />;
  }
  if (artifact.preview?.kind === 'text' && artifact.preview.text) {
    if (artifact.mime_type === 'text/markdown') {
      const lines = artifact.preview.text.replace(/\r\n/g, '\n').split('\n');
      const first = lines.findIndex(line => line.trim());
      const title = /^#\s+(.+)$/.exec(lines[first] ?? '');
      const body = title && title[1].trim().toLowerCase() === artifact.title.trim().toLowerCase()
        ? lines.slice(first + 1).join('\n') : artifact.preview.text;
      return <div className="artifact-document-preview"><Markdown text={body} /></div>;
    }
    return <pre className="artifact-text-preview">{artifact.preview.text}</pre>;
  }
  return <div className="artifact-preview-empty">
    <strong>{artifact.title}</strong>
    <span>A visual preview was not included with this output.</span>
  </div>;
}

export function ArtifactCard({ event }: { event: RunEvent }) {
  const artifact = artifactSchema.parse(event.data);
  const [open, setOpen] = useState(false);
  const Icon = icons[artifact.artifact_type];
  const canPreview = Boolean(artifact.preview || artifact.description || Object.keys(artifact.metadata).length);
  return <article className={`artifact artifact-${artifact.artifact_type}`} aria-label={`${labels[artifact.artifact_type]} output: ${artifact.title}`}>
    <div className="artifact-icon" aria-hidden="true"><Icon size={21} /></div>
    <div className="artifact-copy">
      <span className="artifact-kind">{labels[artifact.artifact_type]}{artifact.provider ? ` · ${artifact.provider.replaceAll('_', ' ')}` : ''}</span>
      <strong>{artifact.title}</strong>
      {artifact.description && <span>{artifact.description}</span>}
    </div>
    <div className="artifact-actions">
      {canPreview && <button className="icon-button" type="button" aria-label={`Preview ${artifact.title}`} title="Preview" onClick={() => setOpen(true)}><Eye size={17} /></button>}
      {artifact.url && <a className="icon-button" href={artifact.url} target="_blank" rel="noreferrer noopener" aria-label={`Open ${artifact.title}`} title="Open"><ExternalLink size={17} /></a>}
    </div>
    {open && <dialog className="artifact-dialog" open aria-modal="true" aria-label={`Preview ${artifact.title}`} onKeyDown={event => { if (event.key === 'Escape') setOpen(false); }}>
      <button className="artifact-backdrop" aria-label="Close preview" onClick={() => setOpen(false)} />
      <section>
        <header><div className="artifact-icon" aria-hidden="true"><Icon size={19} /></div><div><span>{labels[artifact.artifact_type]}</span><strong>{artifact.title}</strong></div>
          <button className="icon-button" type="button" aria-label="Close preview" autoFocus onClick={() => setOpen(false)}><X size={18} /></button>
        </header>
        <div className="artifact-preview"><Preview artifact={artifact} /></div>
        {Object.keys(artifact.metadata).length > 0 && <dl className="artifact-metadata">{Object.entries(artifact.metadata).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>}
        {artifact.url && <footer><a className="artifact-open" href={artifact.url} target="_blank" rel="noreferrer noopener">Open in {artifact.provider?.replaceAll('_', ' ') ?? 'provider'}<ExternalLink size={14} /></a></footer>}
      </section>
    </dialog>}
  </article>;
}