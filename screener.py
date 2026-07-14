name: 실적 스크리닝 일일 갱신
on:
  schedule:
    - cron: '0 22 * * *'
  workflow_dispatch: {}
permissions:
  contents: write
jobs:
  screen:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: 스크리너 실행
        env:
          DART_KEY: ${{ secrets.DART_KEY }}
          LATEST_YEAR: '2026'
          LATEST_Q: '1'
        run: python screener.py
      - name: 내부자 매수 스크리너 실행
        env:
          DART_KEY: ${{ secrets.DART_KEY }}
          DAYS: '30'
        run: python insider.py
      - name: 결과 커밋
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add public/data/screener.json public/data/insider.json
          git commit -m "스크리닝 갱신" || echo "변경 없음"
          git push
