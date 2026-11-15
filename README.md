# Streak — Giữ lửa mỗi ngày

Tool giữ chuỗi TikTok với giao diện web chạy trên Windows. Python điều khiển Chrome/Edge, trang web hiển thị danh sách người nhận, nội dung tin, lịch gửi hằng ngày và nhật ký trực tiếp. Giao diện dùng dữ liệu thật của phiên chạy. Danh sách hiện cả các cuộc trò chuyện chưa xác minh được chuỗi, với nhãn riêng và khóa gửi tự động.

## Bắt đầu

1. Cài Python 3.10+ có Python Launcher (`py`) và Google Chrome hoặc Microsoft Edge.
2. Chạy `setup.bat` một lần.
3. Chạy **`start-windows.bat`** để chạy bản Windows cục bộ. Trang **http://127.0.0.1:8765** tự mở trên trình duyệt.
4. Bấm **Kết nối TikTok**, đăng nhập trong cửa sổ Chrome/Edge được tool mở, vào **Tin nhắn**. Chọn trình duyệt ở chân danh sách bạn bè nếu cần đổi sang Edge.
5. Quay về bảng điều khiển, bấm **Quét danh sách**. Sau khi đọc danh sách, tool tự kiểm tra lịch sử của các cuộc trò chuyện còn hoạt động gần đây; tiến độ hiển thị trong lúc quét.
6. Tool tự chọn chat có bằng chứng chuỗi; soạn tin rồi bấm **Gửi một lượt** để kiểm tra/gửi một đợt, hoặc **Bật giữ chuỗi** để tự kiểm tra và gửi sau 00:00 mỗi ngày theo giờ của trình duyệt.

Bạn có thể tìm tên, chọn tất cả kết quả đang lọc và xem trước tin nhắn. Nội dung và cấu hình được lưu tự động. Khi bật sẽ kiểm tra ngay; những ngày sau bắt đầu kiểm tra/gửi từ 00:00, bỏ qua chat đã rep trong ngày. Khi đang tự động, bấm **Dừng tác vụ** để sửa cấu hình.

Máy cần thức, ứng dụng và cửa sổ TikTok cần được giữ mở. Đóng tab bảng điều khiển không dừng tác vụ; mở lại địa chỉ trên để tiếp tục theo dõi. Bấm **Tắt ứng dụng** trong menu trái để dừng backend. `start-desktop.bat` mở giao diện Tkinter cũ khi cần; dùng một giao diện điều khiển TikTok tại một thời điểm.

## Đăng nhập và nhận diện chuỗi

Tool mở Chrome/Edge đã cài với hồ sơ riêng, lưu trong `browser-profile/`. Không thay hồ sơ trình duyệt thường dùng. Mật khẩu, SMS và xác minh được nhập trực tiếp trên TikTok; tool không tự vượt CAPTCHA hay xác minh đăng nhập.

Sau khi đăng nhập, tên hiển thị, @username và ảnh đại diện thật xuất hiện ở thanh bên và góc trên của bảng điều khiển. Tool kiểm tra tài khoản mỗi 3 giây; có thể bấm biểu tượng cập nhật bên cạnh tài khoản để kiểm tra ngay. Khi mở lại ứng dụng, tool tự khôi phục hồ sơ Chrome/Edge đã lưu. Khi nhận ra tài khoản đã đăng nhập, tool tự quét danh sách cuộc trò chuyện và đối chiếu chuỗi một lần; sau khi hoàn tất tool tự chọn các chat đủ bằng chứng chuỗi; bạn chỉ cần bấm Gửi một lượt hoặc Bật giữ chuỗi. Các chat đã rep vẫn được chọn để theo dõi các ngày sau nhưng bị bỏ qua trong ngày hiện tại. Quét danh sách không tự bật gửi tin. Danh sách được lưu riêng theo tài khoản và trình duyệt trong `conversation-cache.json`. Khi mở lại, tool hiện danh sách đã lưu sau khi xác nhận đúng tài khoản, rồi cập nhật nền; dữ liệu đã lưu chưa được phép gửi cho đến khi cập nhật xong. Quét lại hoặc lỗi quét không xóa danh sách đang có. Trang TikTok đang tải lại được coi là chưa xác định, không phải đăng xuất; chỉ xác nhận đăng xuất khi thấy dấu hiệu rõ ràng lặp lại ít nhất 6 giây. Đổi sang một tài khoản đã đăng nhập khác vẫn được nhận diện ngay khi đọc được danh tính mới. Nếu đăng xuất hoặc đổi tài khoản, tool dừng tự động và xóa danh sách người nhận cũ. Giao diện web không thay đổi cơ chế đăng nhập TikTok hiện có.

Adapter đọc danh sách chat thực tế và đối chiếu metadata cuộc trò chuyện đang có trong client TikTok, đồng thời kiểm tra huy hiệu hiển thị. Emoji trong tin, thông báo chuỗi cũ và metadata lời mời không đủ chứng minh chuỗi hiện tại. Khi dữ liệu chưa xác nhận được, dòng được đánh dấu **Chưa xác minh**; không thể chọn để gửi. Có bộ lọc Tất cả / Đã xác minh có lửa / Chưa xác minh. Chỉ số chuỗi hiển thị — khi chưa thể xác minh, thay vì coi đó là không có chuỗi.

Bộ quét web hiện đọc thêm lịch sử qua SDK nhắn tin đang có trong trang TikTok. Một dòng được gắn **Theo lịch sử** khi có thông báo hệ thống mở chuỗi, đạt mốc hoặc khôi phục chuỗi của TikTok, có trao đổi hai chiều trong mọi ngày đã kết thúc sau ngày thông báo đến hôm qua, và không có thông báo kết thúc xuất hiện sau đó. Ngày khôi phục không cần có đủ tin hai chiều; chuỗi vừa khôi phục hôm nay được nhận diện ngay, không phải đợi thêm 3 ngày. Khoảng trống sau ngày khôi phục vẫn chặn xác minh. Tin hệ thống, lời mời, tin bị thu hồi hoặc chưa gửi thành công không được tính thành trao đổi. Bộ quét không đánh dấu đã đọc khi lấy lịch sử và không lưu nội dung tin nhắn.

Số **≥N ngày** là mức tối thiểu từ bằng chứng đã tải, chưa phải bộ đếm hiện tại do API chuỗi TikTok trả về. Với chuỗi vừa khôi phục, mức sàn 3 ngày dựa trên thông báo TikTok xác nhận có chuỗi; không có nghĩa đã quan sát được 3 ngày nhắn tin sau khôi phục. Cách này có thể bỏ sót nếu không tải đủ lịch sử hoặc thay đổi múi giờ. Bộ quét nhận cả chat riêng và nhóm đang tham gia; thông báo nhóm được nhận diện riêng. Với nhóm, lịch sử cần có ít nhất 2 người gửi khác nhau trong mỗi ngày sau thông báo, không bắt buộc chính bạn tham gia mọi ngày. Những trường hợp thiếu bằng chứng vẫn bị khóa gửi. Mỗi lượt gửi sẽ kiểm tra lại lịch sử và ID cuộc trò chuyện, kiểm tra bản nháp, rồi đợi xác nhận gửi từ client TikTok. Kiểm tra trực tiếp đã nhận diện được các cuộc trò chuyện theo nguồn thông báo hệ thống và lịch sử; chưa gửi tin thật trong quá trình phát triển.

Trước mỗi lần gửi, tool đọc lịch sử hôm nay của đúng chat, kiểm tra lại lần nữa sau khi mở chat. Nếu chính tài khoản đã gửi thành công bất kỳ tin nhắn/video được hỗ trợ hôm nay, kể cả gửi thủ công bằng điện thoại, tool bỏ qua. Tin người khác gửi, tin hệ thống, tin lỗi hoặc đã thu hồi không được coi là bạn đã rep. Nếu chưa đọc hết dữ liệu để xác định có rep hay chưa, tool cũng bỏ qua để tránh gửi trùng. Trạng thái đã rep chỉ có hiệu lực đến hết ngày theo múi giờ trình duyệt; qua ngày mới sẽ kiểm tra lại. Không còn phải chờ đủ 20 giờ: qua 00:00 của ngày mới, chat chưa được chính tài khoản rep sẽ được kiểm tra/gửi tiếp dù tin hôm trước mới gửi lúc 23:59. Khi bật giữa ngày, tool kiểm tra ngay; chat đã rep hôm nay được bỏ qua. Lượt kiểm tra chờ sát mốc 00:00 rồi kiểm tra định kỳ trong ngày để xử lý chat chưa gửi được. Máy ngủ/tắt hoặc mất mạng không thể gửi đúng mốc; khi tool đang hoạt động trở lại sẽ kiểm tra ngày hiện tại. Bộ lọc **Chưa rep hôm nay / Đã rep hôm nay** giúp xem riêng các chat này.

Tool gửi tin theo lịch, chưa đọc nội dung tin đến để tự trả lời. Chuỗi còn phụ thuộc người nhận và [quy tắc TikTok](https://support.tiktok.com/en/using-tiktok/messaging-and-notifications/streaks).

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

## VPS đang triển khai

Tool đã được cài riêng tại VPS Ubuntu `160.250.180.133`, thư mục `/opt/tiktok-streak`.

- Bảng điều khiển: **https://160.250.180.133:8443/**.
- Màn hình Chrome để đăng nhập/xác minh TikTok: **https://160.250.180.133:8443/browser/**, hoặc bấm **Màn hình Chrome** trong menu trái.

Mở trực tiếp các link trên bằng máy tính hoặc điện thoại. Nếu chưa đăng nhập, trang **Đăng nhập** của tool tự xuất hiện; dùng tài khoản web riêng đã cấp. Phiên được nhớ 7 ngày trên trình duyệt. Nút **Đăng xuất** ở góc trên chỉ đăng xuất trang quản lý; tài khoản TikTok và lịch gửi trên VPS vẫn hoạt động. Không cần chạy file `.bat` hay mở SSH. Thông tin truy cập được lưu riêng trên máy Windows tại `C:\Users\Lwent\.ssh\tiktok-streak-web-access.json`; không nằm trong dự án. `start.bat` và `start-vps.bat` chỉ là lối tắt mở link dashboard; `open-browser-vps.bat` mở link Chrome.

Sau khi bấm **Bật giữ chuỗi**, có thể đóng trang và tắt máy cá nhân; VPS tiếp tục chạy theo giờ Việt Nam. **Dừng giữ chuỗi** dừng lịch gửi và vẫn giữ trang quản lý hoạt động. Dịch vụ lưu lựa chọn đã bật trong `automation.json` và chỉ tiếp tục sau khởi động lại khi xác nhận đúng tài khoản cùng các chat đã chọn. Chưa bật lịch thì việc mở trang không tự gửi tin.

`start-vps-ssh.bat` giữ cách kết nối SSH cũ khi cần dùng dự phòng qua `http://127.0.0.1:8765`. `start-windows.bat` chạy riêng bản cục bộ. Hướng dẫn dịch vụ nằm trong `deploy/README.md`.
