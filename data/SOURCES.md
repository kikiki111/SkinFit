# 口コミ媒体の規約確認結果

## 判定一覧

| 媒体 | 判定 | 根拠の要点 | 確認日 |
|------|------|------------|--------|
| @cosme | 手動のみ | 利用規約で無断転載・再配布を禁止。WebFetchは文字化けで本文取得不可 | 2026-10-15 |
| LIPS | 手動のみ | 利用規約第3条第11号でロボット等の自動手段による利用を明示的に禁止 | 2026-10-15 |
| Amazon.co.jp | 使わない | robots.txtでClaudeBot等を全面禁止。レビューページもDisallow。WebFetchは503エラー | 2026-10-15 |
| メーカー公式EC | 手動のみ | 各社とも利用規約で事前許諾なしの複製・転載を禁止 | 2026-10-15 |

## 各媒体の詳細

### 1. @cosme（https://www.cosme.net/）

**robots.txt（https://www.cosme.net/robots.txt）**
- 認証・会員関連ページ（ログイン、サインアップ等）をDisallow（18行）
- APIエンドポイント（`/api/`, `/categories/api/`, `/tags/api/`）をDisallow
- プレビュー、アフィリエイトパラメータ付きURL等の重複ページをDisallow
- **商品の口コミページのパス（/products/）は明示的にDisallowされていない**

**利用規約（https://www.cosme.net/html/prv/rules.html）**
- 第六条（メンバーの禁止事項）第十六号: 「当社からの電子メール、または本サービス内の文章・画像などの情報を無断で転載及び再配布する行為」を禁止
- 第七条第二項: 当社が承認した場合を除き、本サービスを営利目的で利用することを禁止
- 第九条第三項: 著作権には著作権法第二十七条および第二十八条所定の権利（翻訳権・翻案権等）が含まれる
- **自動収集（クローリング・スクレイピング）を直接禁止する条文はないが、転載・再配布の禁止条項が該当する可能性が高い**

**口コミページの取得テスト**
- テストURL: https://www.cosme.net/products/338068/
- 結果: **文字化けが発生し、本文を正常に取得できず**。エンコーディングの問題と推定

### 2. LIPS（https://lipscosme.com/）

**robots.txt（https://lipscosme.com/robots.txt）**
- `/products.*`（商品検索）、`/posts/search`、`/users/search` 等の検索ページをDisallow
- `/chats/`, `/clip_folders/`, `/coupons/` 等の機能ページをDisallow
- 商品フィルタやソートパラメータ付きURLを多数Disallow
- `/users/n/`（未登録ユーザー）、`/users/sign_up`, `/users/sign_in` をDisallow
- **Allow規則**: `/products/*/review` への明示的なAllowあり（検索・フィルタ以外の単純な口コミページは許可の可能性）
- 特定クローラー（Bytespider, meta-externalagent, meta-webindexer）を全面禁止（`Disallow: /`）

**利用規約（https://lipscosme.com/policy）**
- 第3条（禁止事項）第11号: **「ロボットその他の自動手段により本サービスを利用する行為」を明示的に禁止**
- 第4条第3項: 本コンテンツを「サービスが当然に予定している利用態様を超えて利用（複製、送信、転載、改変などの行為を含みます。）してはなりません」
- 第4条第2項: 投稿コンテンツの権利は利用者が保持するが、公開投稿については当社に対し複製・翻訳・翻案・改変等の利用権を無償・無期限で許諾

**口コミページの取得テスト**
- テストURL: https://lipscosme.com/products/617423
- 結果: **商品名と口コミ本文を正常に取得可能**
  - 商品名: Anua PDRNヒアルロン酸カプセル100セラム
  - 口コミ例: 「水のようなサラッとしたテクスチャー 肌馴染み良くしっとりツヤ肌仕上がり」等
- **ただし、利用規約で自動手段による利用を明示的に禁止しているため、エージェントによる自動取得は規約違反**

### 3. Amazon.co.jp（https://www.amazon.co.jp/）

**robots.txt（https://www.amazon.co.jp/robots.txt）**
- アカウント・サインインページ（`/ap/signin`, `/gp/sign-in` 等）をDisallow
- カート・決済ページ（`/gp/cart`, `/gp/item-dispatch` 等）をDisallow
- **レビュー関連ページを多数Disallow**:
  - `/gp/customer-reviews/write-a-review.html`
  - `/gp/customer-media/upload`
  - `/gp/customer-images`
  - `/dp/rate-this-item/`
  - `/gp/vote`, `/gp/voting/`
  - `/review/dynamic/sims-box` 等
- **特定ボットを全面禁止（`Disallow: /`）**: GPTBot, CCBot, ClaudeBot, PerplexityBot, Google-Extended, Bytespider 他多数
- **ClaudeBotは明示的に全ページへのアクセスを禁止されている**

**利用規約（https://www.amazon.co.jp/gp/help/customer/display.html?nodeId=GLSBYFE9MGKKQXXM）**
- 取得不可（503 Service Unavailable エラー）
- 未確認: ロボット・自動収集に関する条文の有無

**商品ページの取得テスト**
- テストURL: https://www.amazon.co.jp/dp/B07TYJW37Q
- 結果: **500 Internal Server Error。WebFetchによる取得不可**

### 4. メーカー公式EC

#### 資生堂ワタシプラス（https://www.shiseido.co.jp/）

**robots.txt（https://www.shiseido.co.jp/robots.txt）**
- Disallow規則は少ない（4行のみ）:
  - Applebot: `/sw/member/auth/SWFG011010.seam`
  - 全クローラー: `/listener/html/`, `/*brnd_cd=`, `/*bi=`
- **口コミページの明示的な禁止はなし**
- 16個のサイトマップとllms.txtファイルを登録
- GPTBot, OAI-SearchBot, ChatGPT-Userには `allow: .*` を設定

**利用規約（https://www.shiseido.co.jp/term_of_use.html）**
- 取得不可（404 Not Found エラー）。正しいURLが不明
- 代替として確認したページ（同ドメイン内の別規約と推定）の内容:
  - 第8条（著作権その他知的財産権）第1項: **「自らの個人利用目的以外に利用したり、ネットワークの内外を問わず、公衆に再提供したり、無断使用・複製等することを禁止します。」**
  - 第6条第9号: 本サービスの運営を妨げる行為を禁止
  - 第14条第1項: 本ウェブサイトへのリンク設定は自由だが、公序良俗違反・法令違反・誹謗中傷・企業価値毀損にあたるサイトからのリンクは禁止

#### 花王（https://www.kao.com/jp/）

**robots.txt（https://www.kao.com/jp/robots.txt）**
- 取得不可（404 Not Found エラー）
- 未確認: Disallow規則の有無

**利用規約（https://www.kao.com/jp/terms-of-use/）**
- 利用範囲: **「掲載コンテンツ（画像、音声、文章等）は、事前の文書による許諾がない限り、複製、頒布、改変、公衆送信、再利用、転送などを含む使用を禁止」**
- 例外: 個人的・非営利的かつ家庭内での利用に限り、コンテンツの一部のみダウンロード可
- 商標類の使用: 事前許諾がない限り、サイト上の名称・商標・ロゴ・サービスマークの不正使用を禁止
- **自動収集（クローリング・スクレイピング）や引用を直接扱う条文はなし**

## 口コミの扱いの方針

### データ収集の原則

**自動収集を避け、手動での要約とURL提示を基本とする**

1. **エージェントによる自動取得を行わない**
   - LIPSは利用規約で「ロボットその他の自動手段による利用」を明示的に禁止
   - Amazonはrobots.txtでClaudeBotを全面禁止し、レビューページもDisallow
   - @cosmeとメーカー公式ECは、規約で無断転載・複製を禁止

2. **人が読んで短く要約し、URLを示す**
   - 原文を長く再掲せず、100字以内の要約にとどめる
   - 必ず元の口コミページのURLを併記する
   - 投稿者のユーザー名・プロフィール情報は保持しない

3. **著作権と利用規約の遵守**
   - 口コミは投稿者の著作物であり、プラットフォームが利用権を持つ
   - 引用の範囲（著作権法第32条）を超える複製・転載は避ける
   - 商用利用にあたる場合は、各プラットフォームの事前承認が必要

4. **個人情報の保護**
   - 投稿者の個人を特定できる情報（氏名・年齢・肌タイプ等）は保持しない
   - 要約時は、効果や使用感のみを抽出し、個人情報は削除する

### 推奨される実装方針

- **手動キュレーション**: 担当者が口コミを読み、要点を100字以内で要約
- **URL参照方式**: アプリ内には要約のみを表示し、詳細はリンク先の元ページで確認してもらう
- **データの最小化**: 口コミの全文やメタデータ（投稿者情報・投稿日時等）をデータベースに保存しない
- **定期的な規約確認**: 各プラットフォームの利用規約は変更される可能性があるため、実装前に最新版を確認

---

**確認日**: 2026-10-15  
**確認者**: データ収集担当  
**次回確認予定**: 実装開始前（規約変更の可能性を考慮）
