module.exports = {
  root: true,
  env: {
    browser: true,
    es2021: true,
  },
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "script",
  },
  ignorePatterns: ["backend/**", "node_modules/**"],
  rules: {
    "no-undef": "error",
    "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    "no-unreachable": "error",
  },
};
