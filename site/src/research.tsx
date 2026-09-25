import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ResearchLabApp } from './research/ResearchLab';
import './styles.css';

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <ResearchLabApp />
  </StrictMode>
);
