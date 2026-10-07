import React from 'react'
import ReactDOM from 'react-dom/client'
import { Toaster } from 'react-hot-toast'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: '#1e293b',
          color: '#f1f5f9',
          border: '1px solid #334155',
        },
        success: { iconTheme: { primary: '#22c55e', secondary: '#1e293b' } },
        error:   { iconTheme: { primary: '#ef4444', secondary: '#1e293b' } },
      }}
    />
  </React.StrictMode>
)
