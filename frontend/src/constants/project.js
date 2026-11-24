export const topic = {
  "name": "陶驿窑务·预检记录分片",
  "direction": "分片放置与搬迁预算",
  "modules": [
    "窑口节点",
    "预检批次",
    "重分片预算",
    "搬迁清单"
  ],
  "algorithm": "加权 Rendezvous Hash 重算候选归属，结合每轮搬迁字节预算生成可执行计划"
};
