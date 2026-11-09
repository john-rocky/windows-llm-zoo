# PLAN — 合否の線と測り方(測る前に書いた: 2026-11-07 14:55 JST)

## 1. 合否の線(出力の check)
- **線 = edge-llm-bench の textCheck**(`android/bench/parsers.text_integrity`、Windows の行の record と同じ関数を Mac で decoded の文にかける): 英数字 32 字以上かつ違う語 10 以上、task の語(`on.device|phone|local|cloud|offline|privacy|\bai\b`)がある、4 行以上で同じ行が半分を超えない。数える run の cold と warm の両方。FAIL の run は数に入れない(bench の text-check-rule)。cell の欄は `n/n PASS`。
- 計器(線ではない): 同じ cell の 3 run の cold の文が同じか(greedy の再現)、止まった理由(EOS / 128 token)、生成した token 数。
- 落ちた cell(load・compile・生成で落ちる)は error の全文、runtime と EP の版、command を JSON に(status = error)。

## 2. workload(bench の short-chat に揃える)
- prompt = `edge-llm-bench/prompts/text/short-chat.txt` の文(sha256 を JSON に)を user の 1 発話として、各 runtime の chat template(package の既定)で包む。Qwen3 は template の既定 = thinking あり(bench の LiteRT-LM・llama.cpp の行と同じ)、Gemma 4 は package の既定(thinking の切り替えは触らない)。包んだ後の prompt の token 数を JSON に。
- greedy、出力は最大 128 token(EOS で止まる)、context は runtime が取る所で 2048(ORT GenAI = `max_length` 2048、bench の `--max_num_tokens=2048` / `-c 2048` と同じく KV を 2048 で取る)。Foundry Local は package の genai_config の context(catalog の物、E4B の local は 8K)= JSON に書く。OpenVINO GenAI の CPU / GPU は KV を動的に取る、NPU は静的な形(既定の MAX_PROMPT_LEN 1024 + MIN_RESPONSE_LEN 128)= JSON に書く。
- 1 run = 新しい engine の process 1 つ(Foundry は新しい daemon 1 つ: `server stop` → `server start` → `model load`)、その中で同じ prompt を 2 回(1 回目 = cold、2 回目 = warm、毎回新しい generator / request)。bench の LiteRT-LM の行(`--num_iterations=2`)と同じ形。表の headline = cold(bench の Windows の regime)。

## 3. 数え方(bench と同じ)
- 1 cell = 3 run(続けて、run の間に 30 s 休む = bench の `-BetweenRunsSeconds`)。
- GPU と NPU の cell は run 1(その sitting でその cell の最初の process)を数えない = bench の Vulkan・CUDA・LiteRT-LM の行の `firstEver` と同じ扱い(n = 2)。CPU の cell(ORT GenAI CPU EP、OpenVINO EP の CPU、OpenVINO GenAI の CPU(cache dir なし)、Foundry の CPU の variant)は disk に cache を書かない = bench の llama.cpp CPU の行と同じく 3 run とも数える(n = 3)。
- cold の spread((max − min) / median)が 5 % を超える cell は `out`(bench の spread-rule)。同じ sitting の最後にもう 1 回(`-rerun`)取り、数えられればその数を使い名を書く。
- 数 = 数える run の cold の中央値。decode tok/s・prefill tok/s・TTFT・peak memory を同じ run の組から。

## 4. 指標の切り方(runtime ごと。差は表の注に書く)
| runtime | decode tok/s | prefill tok/s | TTFT |
|---|---|---|---|
| LiteRT-LM、llama.cpp(既の行) | bench の parser(engine の報告) | 同 | LiteRT-LM = engine の報告、llama.cpp = なし(bench の parser は導かない) |
| ORT GenAI(Python 直) | 2..N 個目の token / それらの `generate_next_token` の wall の和(bench の ORT GenAI の腕 = `scripts/ortgenai_mac.py` の Timing) | prompt の token 数 / `append_tokens(prompt)` の wall | `append_tokens` + 最初の `generate_next_token` |
| Foundry Local(REST、streaming) | (content の chunk 数 − 1)/(最後の chunk − 最初の chunk)(`john-rocky/gemma-4-e4b-on-foundry-local` の `fl_rest.py` と同じ: 1 chunk = 1 token) | prompt の token 数(usage)/ TTFT(HTTP と template を含む = 上限側) | request の送信 → 最初の content の chunk |
| OpenVINO GenAI | 1000 / TPOT の平均(`perf_metrics.get_tpot()`、最初の token の後) | 入力の token 数 / TTFT | `perf_metrics.get_ttft()` |
- short-chat の prompt は 19〜20 token = prefill tok/s は固定の手間でほぼ決まる(この PC の別の計測の注: LiteRT-LM の Qwen3 は 1 回の prefill の時間が token 数に依らない。ここでは確かめていない)= 量の速さとして読まない。表の注に書く。
- peak memory = engine の process の PeakWorkingSet(bench の `rssBasis` と同じ量: ORT GenAI と OpenVINO GenAI は Python の process が終わる前に自分の `GetProcessMemoryInfo`、Foundry は daemon の `PeakWorkingSet64` を server stop の前に)。GPU の memory は別の列: process の `\GPU Process Memory(pid_<pid>_*)\Dedicated Usage` と `Shared Usage` の最大(2 s ごと、luid で adapter を分ける)。

## 5. sitting と anchor(別の時刻の数を並べるため)
- PC の数は日をまたぐと −20〜+6 % 動く(この PC の別の計測の記録、ここでは確かめていない)。この repo の計時は sitting ごとに頭と終わりに **anchor**: bench の行 4 本を bench の executor で(records は `raw/anchors/`、`BENCH_RAW_ROOT` = bench の summary に入れない)。Gemma 4 E2B の `litert-lm` cpu・npu、`llama.cpp` cuda(RTX)、Qwen3 1.7B の `litert-lm` gpu `adapter=igpu`(Intel GPU、この PC の別の計測の 2 回で spread 0.18 / 0.52 %、ここでは確かめていない)。各 runs=3。
- 表は sitting の名と、その sitting の anchor が bench の表の sitting(`2026-11-07-windows-e4b` / `-igpu`)からどれだけ動いたかを装置ごとに 1 行で書く。anchor が 5 % を超えて動いた装置は、その sitting のこの repo の数と bench の数の差を読まないと注に書く。

## 6. 静かさ(この PC を分け合う決まり)
- 計時の sitting は `%USERPROFILE%\pcup\busy.txt` を CreateNew で取る(label `Z2` = 共用 PC の鍵の file の上での、この repo の名前)。他の計測の 2 時間より新しい印がある間は始めない(PC 側の 1 本の ssh の loop で 5 s ごとに待つ、Mac から poll しない)。取った後の門 = 5 s の CPU の標本 3 回続けて 15 % 未満 + 他の process の RTX の memory 0 MiB + build の道具(cl・link・MSBuild・cmake・ninja・nvcc・cicc・ptxas)の CPU 秒の差の和 < 200 ms(この PC の別の計測が使っていた形)、上限 10 分(開かなければ鍵を返して待ち直す)。
- run ごとの門 = bench の job と同じ: CPU 3 読み(1 s おき)で 25 % 未満、NVIDIA の memory 800 MiB 未満、Intel GPU の cell は GPU engine の和 10 % 未満、上限 30 分(越えたら `gate: timeout` を JSON に)。run の前後に CPU と top process(1 s の窓)を JSON に。空き RAM 8 GB 未満なら待つ。**(2026-11-07 15:35 訂正)** 空き RAM の線は cell ごと = 棚の大きさ × 1.2 + 2 GB(`tools/make_plan.py` の `ram_need_gb`、2.6〜10.3 GB): 15:33 に他の計測の 1 process が 21 GB を持ち空きが 5.5 GB で、固定の 8 GB では 0.6B の cell も 30 分待つ。線は paging を避けるためで、cell の必要量で足りる。
- 鍵の duty: 他の計測が待っている間(`pcup\yield\*.txt` か自分以外の `active\*.txt`)は、鍵を 30 分持ったら cell の区切りで外して 15 分空け、取り直して門を通る。**(2026-11-08 06:1x 訂正: 空けるのは 16.5 分(15 分空いた後に取る計測と取り直しが競わない)、取り直した後に 60 s の settle。計時の間は自分の untimed の工程を走らせない・suspend で置かない = `pc\lock.ps1 take` が断る)**鍵の時刻は cell ごとに書き直す。**(2026-11-09 訂正: 今の形は README の「Shared-PC conventions」)**
- 静かさの要らない工程(download、venv、first pass)は `pcup\active\Z2.txt` に「何を・いつから」を書き、`%USERPROFILE%\pcup\yield_run.ps1 -Lane Z2 -Cmd "<cmd>"` の下で回す(他の計測の鍵で止まる。`yield_run.ps1` は共用 PC の script で、この repo には無い)。計時の間に新しい ssh を開かない(待ちは PC 側の 1 本の長い ssh、done の file)。

## 7. 置き場
- PC: `C:\src\llmzoo\`(venv、model、runs、logs)= この repo の物だけ。他の計測の file(Foundry の cache の他の model など)は読むだけ。
- Mac: `raw/<sitting>/`(PC から 1 接続の tar で引く)、`results/<model>/<cell>.json`(`tools/build_results.py` が raw から作る、既の cell は `tools/collect_bench.py`)、表 = `tools/table.py` → `RESULTS_LLM_WINDOWS.md`。

## 8. 公開
- runtime をまたぐ表は公開しない: `tools/table.py` で手元に作る(edge-llm-bench の CLAUDE.md と同じ決まり: "Cross-runtime standings stay LOCAL ... Cross-runtime speed comparison is published for Gemma-4 only, and in the archive repo, not here.")。公開するのは harness と records(cell ごとの JSON)。TensorRT-RTX と TensorRT-Edge-LLM は測らない・書かない、`NvTensorRtRtx` EP は使わない。
