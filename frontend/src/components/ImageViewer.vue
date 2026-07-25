<script setup lang="ts">
withDefaults(defineProps<{
  src: string;
  size?: number;
}>(), { size: 120 });
</script>

<template>
  <img :src="src" class="thumb" :style="{ width: size + 'px', height: size + 'px' }" />
</template>

<style scoped>
.thumb {
  border-radius: var(--radius);
  object-fit: cover;
  border: 1px solid var(--border);
  cursor: pointer;
}
</style>
