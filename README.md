# SKACHKOV A17 Lab — обновление рассадки и выбора позиции

Состав:
- export_preflop_ranges_v3.py — расширенный экспортёр с равномерной ротацией рассадки и исправленным Fold to Steal
- a17-lab/index.html — HTML-панель: одна / две / разница матриц, кликабельный покерный стол

1. В GitHub смержить https://github.com/Laosez/Texas-Holdem-AI/pull/2
2. В Codespaces выполнить git pull
3. Загрузить этот ZIP в корневую папку /workspaces/Texas-Holdem-AI и выполнить:
   unzip -o A17_Preflop_Lab_v3_Package.zip
4. Проверить:
   THAI_ENGINE_IMPL=legacy python -m unittest test_seating_rotation test_position_labels -v
5. Запустить:
   THAI_ENGINE_IMPL=legacy python export_preflop_ranges_v3.py \
     --players "smart,gto,tag_punisher,wide_defender,baseline_sane,nit,loose_passive,maniac,pressure_filler" \
     --tournaments 200 --parallel 2 --seed 42 --seat-mode rotate --out ranges_200_v3_rotated

Чтобы открыть панель, открой a17-lab/index.html в браузере и нажми «Выбрать папку результатов».

Важное статистическое ограничение: ротация сбалансирует стартовые места, но не увеличит число раздач на полном 9-max. Для плотной матрицы 169×9 нужен отдельный префлоп-тест с фиксированным полным столом.
