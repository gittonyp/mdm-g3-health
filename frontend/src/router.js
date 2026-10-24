import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", redirect: "/clinic" },
  { path: "/clinic", component: () => import("./views/ClinicView.vue") },
  { path: "/clinic/patient/:id", component: () => import("./views/PatientView.vue") },
  { path: "/care", component: () => import("./views/CareView.vue") },
  { path: "/history", component: () => import("./views/HistoryView.vue") },
  { path: "/live", component: () => import("./views/LiveView.vue") },
  { path: "/:pathMatch(.*)*", component: () => import("./views/NotFoundView.vue") },
];

export default createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});
