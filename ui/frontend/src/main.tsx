import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { RoomApp } from './RoomApp';
import './style.css';

// A desk configured with a room opens on the room; any other desk on its agents.
function Desk() {
  const [workspace, setWorkspace] = useState<{ name: string; room?: boolean } | null>(null);
  useEffect(() => {
    fetch('/api/workspace').then(r => r.json()).then(setWorkspace).catch(() => setWorkspace({ name: 'JarvisCore Agents' }));
  }, []);
  if (!workspace) return null;
  return workspace.room ? <RoomApp workspaceName={workspace.name} /> : <App />;
}

createRoot(document.getElementById('root')!).render(<StrictMode><Desk /></StrictMode>);
