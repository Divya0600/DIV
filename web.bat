@echo off
setlocal

REM Create project folder
set PROJECT_NAME=react_tailwind_offline
mkdir %PROJECT_NAME%
cd %PROJECT_NAME%

echo === Downloading React, ReactDOM, and Babel ===
curl -O https://unpkg.com/react@18/umd/react.development.js
curl -O https://unpkg.com/react-dom@18/umd/react-dom.development.js
curl -O https://unpkg.com/@babel/standalone/babel.min.js

echo === Initializing npm project ===
npm init -y

echo === Installing TailwindCSS ===
npm install -D tailwindcss

echo === Creating Tailwind config ===
npx tailwindcss init

REM Configure Tailwind to scan all HTML files
(
echo module.exports = {
echo   content: ["./*.html"],
echo   theme: { extend: {} },
echo   plugins: [],
echo }
) > tailwind.config.js

echo === Creating Tailwind input.css ===
(
echo @tailwind base;
echo @tailwind components;
echo @tailwind utilities;
) > input.css

echo === Building Tailwind CSS ===
npx tailwindcss -i ./input.css -o ./tailwind.min.css --minify

echo === Creating index.html ===
(
echo ^<!DOCTYPE html^>
echo ^<html^>
echo ^<head^>
echo   ^<meta charset="UTF-8"^>
echo   ^<title^>Offline React + Tailwind^</title^>
echo   ^<link rel="stylesheet" href="./tailwind.min.css"^>
echo ^</head^>
echo ^<body class="p-5"^>
echo   ^<div id="root"^>^</div^>
echo
echo   ^<script src="./react.development.js"^>^</script^>
echo   ^<script src="./react-dom.development.js"^>^</script^>
echo   ^<script src="./babel.min.js"^>^</script^>
echo
echo   ^<script type="text/babel"^>
echo     function App() {
echo       return ^<h1 className="text-3xl font-bold text-blue-500"^>Hello Offline React + Tailwind!^</h1^>;
echo     }
echo     ReactDOM.createRoot(document.getElementById('root')).render(^<App /^>);
echo   ^</script^>
echo ^</body^>
echo ^</html^>
) > index.html

echo === Setup complete! ===
echo Folder: %cd%
echo Open index.html in your browser to test offline.
pause
