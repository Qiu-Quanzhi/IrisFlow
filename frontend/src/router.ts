import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";

const routes = [
  { path: "/", name: "new-chat", component: App },
  { path: "/chat/:sessionId", name: "chat", component: App },
];

export default createRouter({ history: createWebHistory(), routes });
