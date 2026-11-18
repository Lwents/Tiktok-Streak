# Streak — Giữ lửa mỗi ngày

App Windows giữ chuỗi TikTok. Python điều khiển Chrome/Edge, bảng điều khiển hiển thị danh sách người nhận, nội dung tin, lịch gửi hằng ngày và nhật ký trực tiếp. Danh sách hiện cả các cuộc trò chuyện chưa xác minh được chuỗi, với nhãn riêng và khóa gửi tự động.

## Bắt đầu

1. Cài Python 3.10+ có Python Launcher (`py`), Microsoft Edge WebView2 Runtime và Google Chrome hoặc Microsoft Edge.
2. Chạy `setup.bat` một lần.
3. Chạy **`start.bat`** hoặc **`start-windows.bat`** để mở cửa sổ **TikTok Streak** trên máy Windows. Bảng điều khiển chạy trong cửa sổ app bằng WebView2.
4. Bấm **Kết nối TikTok**, đăng nhập trong cửa sổ Chrome/Edge được tool mở, vào **Tin nhắn**. Chọn trình duyệt ở chân danh sách bạn bè nếu cần đổi sang Edge.
5. Quay về bảng điều khiển, bấm **Quét danh sách**. Sau khi đọc danh sách, tool tự kiểm tra lịch sử của các cuộc trò chuyện còn hoạt động gần đây; tiến độ hiển thị trong lúc quét.
6. Tool tự chọn chat có bằng chứng chuỗi; soạn tin rồi bấm **Gửi một lượt** để kiểm tra/gửi một đợt, hoặc **Bật giữ chuỗi** để tự kiểm tra và gửi sau 00:00 mỗi ngày theo giờ của trình duyệt.

Bạn có thể tìm tên, chọn tất cả kết quả đang lọc và xem trước tin nhắn. Nội dung và cấu hình được lưu tự động. Khi bật sẽ kiểm tra ngay; những ngày sau bắt đầu kiểm tra/gửi từ 00:00, bỏ qua chat đã rep trong ngày. Khi đang tự động, bấm **Dừng tác vụ** để sửa cấu hình.

Máy cần thức và app cần mở để tự động theo dõi. Có thể thu nhỏ cửa sổ app. Bấm **Tắt ứng dụng** hoặc đóng cửa sổ để dừng phiên chạy trên Windows. `start-desktop.bat` mở giao diện Tkinter cũ khi cần; dùng một giao diện điều khiển TikTok tại một thời điểm.

## Đăng nhập và nhận diện chuỗi

Tool mở Chrome/Edge đã cài với hồ sơ riêng, lưu trong `browser-profile/`. Không thay hồ sơ trình duyệt thường dùng. Mật khẩu, SMS và xác minh được nhập trực tiếp trên TikTok; tool không tự vượt CAPTCHA hay xác minh đăng nhập.

Sau khi đăng nhập, tên hiển thị, @username và ảnh đại diện thật xuất hiện ở thanh bên và góc trên của bảng điều khiển. Tool kiểm tra tài khoản mỗi 3 giây; có thể bấm biểu tượng cập nhật bên cạnh tài khoản để kiểm tra ngay. Khi mở lại ứng dụng, tool tự khôi phục hồ sơ Chrome/Edge đã lưu. Khi nhận ra tài khoản đã đăng nhập, tool tự quét danh sách cuộc trò chuyện và đối chiếu chuỗi một lần; sau khi hoàn tất tool tự chọn các chat đủ bằng chứng chuỗi; bạn chỉ cần bấm Gửi một lượt hoặc Bật giữ chuỗi. Các chat đã rep vẫn được chọn để theo dõi các ngày sau nhưng bị bỏ qua trong ngày hiện tại. Quét danh sách không tự bật gửi tin. Danh sách được lưu riêng theo tài khoản và trình duyệt trong `conversation-cache.json`. Khi mở lại, tool hiện danh sách đã lưu sau khi xác nhận đúng tài khoản, rồi cập nhật nền; dữ liệu đã lưu chưa được phép gửi cho đến khi cập nhật xong. Quét lại hoặc lỗi quét không xóa danh sách đang có. Trang TikTok đang tải lại được coi là chưa xác định, không phải đăng xuất; chỉ xác nhận đăng xuất khi thấy dấu hiệu rõ ràng lặp lại ít nhất 6 giây. Đổi sang một tài khoản đã đăng nhập khác vẫn được nhận diện ngay khi đọc được danh tính mới. Nếu đăng xuất hoặc đổi tài khoản, tool dừng tự động và xóa danh sách người nhận cũ. Giao diện web không thay đổi cơ chế đăng nhập TikTok hiện có.

Adapter đọc danh sách chat thực tế và đối chiếu metadata cuộc trò chuyện đang có trong client TikTok, đồng thời kiểm tra huy hiệu hiển thị. Emoji trong tin, thông báo chuỗi cũ và metadata lời mời không đủ chứng minh chuỗi hiện tại. Khi dữ liệu chưa xác nhận được, dòng được đánh dấu **Chưa xác minh**; không thể chọn để gửi. Có bộ lọc Tất cả / Đã xác minh có lửa / Chưa xác minh. Chỉ số chuỗi hiển thị — khi chưa thể xác minh, thay vì coi đó là không có chuỗi.

Bộ quét web hiện đọc thêm lịch sử qua SDK nhắn tin đang có trong trang TikTok. Một dòng được gắn **Theo lịch sử** khi có thông báo hệ thống mở chuỗi, đạt mốc hoặc khôi phục chuỗi của TikTok, có trao đổi hai chiều trong mọi ngày đã kết thúc sau ngày thông báo đến hôm qua, và không có thông báo kết thúc xuất hiện sau đó. Ngày khôi phục không cần có đủ tin hai chiều; chuỗi vừa khôi phục hôm nay được nhận diện ngay, không phải đợi thêm 3 ngày. Khoảng trống sau ngày khôi phục vẫn chặn xác minh. Tin hệ thống, lời mời, tin bị thu hồi hoặc chưa gửi thành công không được tính thành trao đổi. Bộ quét không đánh dấu đã đọc khi lấy lịch sử và không lưu nội dung tin nhắn.

Số **≥N ngày** là mức tối thiểu từ bằng chứng đã tải, chưa phải bộ đếm hiện tại do API chuỗi TikTok trả về. Với chuỗi vừa khôi phục, mức sàn 3 ngày dựa trên thông báo TikTok xác nhận có chuỗi; không có nghĩa đã quan sát được 3 ngày nhắn tin sau khôi phục. Cách này có thể bỏ sót nếu không tải đủ lịch sử hoặc thay đổi múi giờ. Bộ quét nhận cả chat riêng và nhóm đang tham gia; thông báo nhóm được nhận diện riêng. Với nhóm, lịch sử cần có ít nhất 2 người gửi khác nhau trong mỗi ngày sau thông báo, không bắt buộc chính bạn tham gia mọi ngày. Những trường hợp thiếu bằng chứng vẫn bị khóa gửi. Mỗi lượt gửi sẽ kiểm tra lại lịch sử và ID cuộc trò chuyện, kiểm tra bản nháp, rồi đợi xác nhận gửi từ client TikTok. Kiểm tra trực tiếp đã nhận diện được các cuộc trò chuyện theo nguồn thông báo hệ thống và lịch sử; chưa gửi tin thật trong quá trình phát triển.

Trước mỗi lần gửi, tool đọc lịch sử hôm nay của đúng chat, kiểm tra lại lần nữa sau khi mở chat. Nếu chính tài khoản đã gửi thành công bất kỳ tin nhắn/video được hỗ trợ hôm nay, kể cả gửi thủ công bằng điện thoại, tool bỏ qua. Tin người khác gửi, tin hệ thống, tin lỗi hoặc đã thu hồi không được coi là bạn đã rep. Nếu chưa đọc hết dữ liệu để xác định có rep hay chưa, tool cũng bỏ qua để tránh gửi trùng. Trạng thái đã rep chỉ có hiệu lực đến hết ngày theo múi giờ trình duyệt; qua ngày mới sẽ kiểm tra lại. Không còn phải chờ đủ 20 giờ: qua 00:00 của ngày mới, chat chưa được chính tài khoản rep sẽ được kiểm tra/gửi tiếp dù tin hôm trước mới gửi lúc 23:59. Khi bật giữa ngày, tool kiểm tra ngay; chat đã rep hôm nay được bỏ qua. Lượt kiểm tra chờ sát mốc 00:00 rồi kiểm tra định kỳ trong ngày để xử lý chat chưa gửi được. Máy ngủ/tắt hoặc mất mạng không thể gửi đúng mốc; khi tool đang hoạt động trở lại sẽ kiểm tra ngày hiện tại. Bộ lọc **Chưa rep hôm nay / Đã rep hôm nay** giúp xem riêng các chat này.

Tool gửi tin/video theo lịch và có chế độ AI trả lời tin mới khi bạn bật. Chuỗi còn phụ thuộc người nhận và [quy tắc TikTok](https://support.tiktok.com/en/using-tiktok/messaging-and-notifications/streaks).

## Tự khôi phục chuỗi

Bật **Tự khôi phục chuỗi** trong phần soạn tin trước khi bật lịch. Tool theo dõi các chat đã chọn, nhận diện thông báo mất chuỗi và dùng lượt khôi phục của tài khoản khi TikTok còn cho phép. Chỉ các chat trong phạm vi bạn đã chọn được xử lý. Các chat có thông báo khôi phục còn hạn có thể được chọn khi bật tùy chọn này; chat chưa xác minh thông thường vẫn bị khóa.

Mỗi 5 phút, lịch đang chạy kiểm tra lại thông báo của các chat đã chọn, kể cả chat bạn đã rep hôm nay. Khôi phục thành công được xác nhận bằng thông báo hệ thống mới trong lịch sử chat. Sau đó tool kiểm tra rep hôm nay và gửi tiếp nếu cần. Bộ lọc **Chuỗi đã mất** hiển thị các thông báo kết thúc; thông báo cũ đã được khôi phục không bị coi là chuỗi vừa mất.

TikTok giới hạn thời gian khôi phục trong 48 giờ sau khi chuỗi kết thúc và áp dụng số lượt của tài khoản. `recovery-state.json` lưu trạng thái từng lần thử trước khi gọi khôi phục. Nếu mất kết nối hoặc chưa xác nhận được kết quả, tool khóa gọi lặp cho cùng tài khoản, chat và lần mất chuỗi; vẫn kiểm tra thông báo xác nhận. Lỗi TikTok đã trả rõ ràng được chờ ít nhất một giờ trước khi thử lại. Không xóa sổ này khi một lần khôi phục còn chưa rõ kết quả. Cookie được đọc trực tiếp từ phiên Chrome/Edge đang đăng nhập và không được lưu trong sổ khôi phục.

## AI trả lời chat và video giữ chuỗi

Bật **AI tự trả lời tin nhắn mới** rồi **Bật giữ chuỗi** để AI theo dõi các chat đã chọn. Tool kiểm tra tin mới khoảng 15 giây một lần, chỉ xử lý tin văn bản đến sau lúc bật và còn trong 24 giờ gần nhất. Mỗi câu trả lời dùng tối đa 12 tin gần nhất, mỗi tin tối đa 700 ký tự. Tin hệ thống và tin bị thu hồi không được dùng. Tệp đính kèm trong ngữ cảnh được thay bằng ký hiệu; chế độ trả lời chat hiện không phân tích nội dung âm thanh hoặc video đính kèm.

Tool đợi khoảng 5 giây để gom tin nhắn liên tiếp, giới hạn một lượt trả lời/phút/chat, và kiểm tra lại người nhận, tin mới nhất cùng tài khoản trước khi gửi. Nếu bạn đã trả lời trong lúc AI soạn, hoặc bạn kia gửi thêm tin, bản nháp cũ được hủy. `ai-replies.json` giữ ID tin đã xử lý và bản nháp do AI tạo, không lưu nội dung chat đầu vào. Trạng thái gửi chưa rõ kết quả khóa thử lại qua các lần khởi động. API key chỉ được backend sử dụng; giao diện chỉ thấy tên model và địa chỉ proxy.

Ở **Giữ chuỗi hằng ngày bằng**, chọn **Video do AI chọn**. Tool tìm video theo từ khóa, đọc mô tả và 3 khung hình ở các thời điểm khác nhau, rồi nhờ model chọn một clip ngắn phù hợp. Phần chọn video hiện không phân tích âm thanh. Mục **Tìm video** cho xem clip đã chọn và lý do. Lựa chọn được giữ cho ngày hiện tại; video đã chọn trong 7 ngày gần đây được tránh chọn lại. Video được chia sẻ bằng loại tin video gốc của TikTok, hỗ trợ chat riêng và nhóm đã tham gia.

Luồng giữ chuỗi hằng ngày bỏ qua chat đã được chính tài khoản rep trong ngày. Luồng AI chat phản hồi tin văn bản mới dù bạn đã rep trước đó. Nếu chưa tìm được video phù hợp, lượt giữ chuỗi dùng tin nhắn đã soạn làm dự phòng. Khi đã bắt đầu chia sẻ mà kết quả chưa rõ, tool khóa thử lại để tránh gửi thêm tin trùng. Tự khôi phục chuỗi vẫn hoạt động cho các chat đã chọn.

Nhập proxy, model và API key trong **Cài đặt gửi → AI và video**. App lưu khóa trong thư mục dữ liệu Windows của người dùng. Khi chỉnh proxy hoặc model, có thể để trống ô API key để giữ khóa đang dùng. Khi chưa có proxy, app vẫn gửi tin nhắn đã soạn và giữ tùy chọn AI đã chọn. Khi bật AI, ngữ cảnh chat được chuyển tới proxy đã cấu hình. Nút **Thử trả lời** chỉ gửi câu mẫu tới proxy.

## Lưu trữ và xử lý lỗi

- `desktop-settings.json`: trình duyệt và nội dung gửi. Trường giờ của bản cũ chỉ được giữ để tương thích dữ liệu; lịch hiện tại là theo ngày. Giao diện tự chọn chat đã xác minh sau khi tải dữ liệu mới. Những chat bạn bỏ chọn được lưu trong trình duyệt, riêng theo tài khoản TikTok và Chrome/Edge; không bị tự chọn lại khi tải trang hoặc quét lại. Việc chọn không tự bật gửi tin. Tác vụ đã bật trong backend vẫn dùng lựa chọn ban đầu.
- `state.json`: lịch sử dùng chung giữa giao diện web và desktop. `sent` nghĩa là đã thấy tin nhắn mới trong chat; chưa chứng minh người nhận đã nhận hoặc chuỗi đã cập nhật.
- `pending`: kết quả lần thao tác trước chưa chắc chắn, tool không tự gửi lại. Kiểm tra chat. Nếu chắc chắn chưa gửi, xóa riêng bản ghi của người đó; nếu đã gửi, sửa `status` thành `sent` và `sent_at` thành Unix timestamp thời điểm gửi.
- `browser-profile/`: phiên đăng nhập riêng cho từng trình duyệt. Không chia sẻ thư mục này.
- `.running.lock`: file đánh dấu khóa hồ sơ trình duyệt. Hệ điều hành tự nhả khóa khi tiến trình thoát hoặc bị tắt cưỡng bức; file vẫn tồn tại và không cần xóa. File còn sót từ bản cũ không ngăn khôi phục phiên đăng nhập.

Các file phiên và cấu hình đã được loại khỏi Git. Server web chỉ lắng nghe trên `127.0.0.1`, không cần đưa dự án lên hosting. Chỉ các yêu cầu từ trang của tool với token hợp lệ mới được thực hiện thao tác.

## Phát triển và kiểm tra

```powershell
.\.venv\Scripts\python.exe web_app.py --open
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Kiểm tra gồm phục hồi phiên Chrome đã đóng, đổi Chrome/Edge, chống gửi sai người trong trang chat giả lập, API web, chọn/lọc người nhận và xem trước tin. Không gửi tin thật trong bộ kiểm tra.

`worker.py` dùng chung cho `web_app.py` và `desktop.py`. `web/` chứa HTML/CSS/JavaScript không cần npm hay bước build. CLI cũ ở `streak.py` dùng `config.json` với URL chỉ định thủ công và không có bộ lọc huy hiệu của giao diện.

## Khi đăng nhập Google báo “This browser or app may not be secure”

Đây là thông báo Google từ chối phiên đăng nhập. Trên bảng điều khiển, bấm **Đăng nhập bằng QR** để mở cách đăng nhập trực tiếp của TikTok, rồi dùng điện thoại quét mã và xác nhận. Sau khi thành công, vào Tin nhắn rồi Quét danh sách. Tool không thay đổi thiết lập bảo mật của Google.
