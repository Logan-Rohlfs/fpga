import '@fontsource/jost/400.css';
import '@fontsource/jost/500.css';
import '@fontsource/jost/600.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import './app.css';
import { mount } from 'svelte';
import App from './App.svelte';
import { applyTheme, loadTheme } from './lib/theme';

applyTheme(loadTheme());
mount(App, { target: document.getElementById('app')! });
