import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "test-results", "playwright-report"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      // No browser storage: drafts live on the server (App-flow.md 4.3).
      "no-restricted-globals": ["error", "localStorage", "sessionStorage", "indexedDB"],
      // No parseFloat or Number() on money: amounts stay strings or integer cents (CLAUDE.md).
      "no-restricted-syntax": [
        "error",
        { selector: "CallExpression[callee.name='parseFloat']", message: "No floats in money or quantity code." },
      ],
    },
  },
);
