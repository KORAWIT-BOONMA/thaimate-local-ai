<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>เว็บไซต์ของฉัน - Fir s</title>
    <!-- นำเข้าฟอนต์จาก Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;700&display=swap" rel="stylesheet">
    <style>
        /* ตั้งค่าทั่วไป */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Sarabun', sans-serif;
            background-color: #f0f4f8; /* สีพื้นหลังโทนขาวอมฟ้าอ่อน */
            color: #333;
            line-height: 1.6;
        }

        /* Header / แถบด้านบน */
        header {
            background-color: #ffffff;
            padding: 20px 50px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }

        .logo {
            font-size: 24px;
            font-weight: bold;
            color: #0056b3; /* น้ำเงินเข้ม */
        }

        nav ul {
            list-style: none;
            display: flex;
        }

        nav ul li {
            margin-left: 20px;
        }

        nav ul li a {
            text-decoration: none;
            color: #333;
            font-weight: 500;
            transition: color 0.3s;
        }

        nav ul li a:hover {
            color: #0056b3; /* เปลี่ยนเป็นน้ำเงินเมื่อเอาเมาส์ชี้ */
        }

        /* Hero Section / ส่วนหลัก */
        .hero {
            height: 80vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            background: linear-gradient(135deg, #e3f2fd 0%, #ffffff 100%); /* เรตินาสีฟ้าอ่อนไปขาว */
            padding: 20px;
        }

        .hero h1 {
            font-size: 48px;
            margin-bottom: 20px;
            color: #0056b3;
        }

        .hero p {
            font-size: 20px;
            margin-bottom: 30px;
            max-width: 600px;
            color: #555;
        }

        .btn {
            display: inline-block;
            background-color: #0056b3;
            color: white;
            padding: 12px 30px;
            border-radius: 30px;
            text-decoration: none;
            font-weight: bold;
            transition: background-color 0.3s, transform 0.2s;
        }

        .btn:hover {
            background-color: #004494; /* น้ำเงินเข้มขึ้น */
            transform: translateY(-3px);
        }

        /* Features Section / ส่วนแสดงเนื้อหา */
        .features {
            padding: 80px 50px;
            text-align: center;
        }

        .features h2 {
            font-size: 32px;
            margin-bottom: 50px;
            color: #0056b3;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 30px;
            max-width: 1200px;
            margin: 0 auto;
        }

        .card {
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.05);
            transition: transform 0.3s;
        }

        .card:hover {
            transform: translateY(-10px);
        }

        .card h3 {
            margin-bottom: 15px;
            color: #333;
        }

        footer {
            background-color: #0056b3;
            color: white;
            text-align: center;
            padding: 20px;
            margin-top: 50px;
        }

    </style>
</head>
<body>

    <header>
        <div class="logo">Fir s's Portfolio</div>
        <nav>
            <ul>
                <li><a href="#">หน้าหลัก</a></li>
                <li><a href="#">เกี่ยวกับฉัน</a></li>
                <li><a href="#">บริการ</a></li>
                <li><a href="#">ติดต่อ</a></li>
            </ul>
        </nav>
    </header>

    <section class="hero">
        <h1>สร้างประสบการณ์ที่ดีให้กับผู้ใช้</h1>
        <p>เว็บไซต์นี้ออกแบบด้วยโทนสีขาวและน้ำเงิน ให้ความรู้สึกสะอาดตา เป็นมืออาชีพ และทันสมัย เหมาะสำหรับผู้ประกอบการและนักพัฒนาเว็บครับ</p>
        <a href="#" class="btn">เรียนรู้เพิ่มเติม</a>
    </section>

    <section class="features">
        <h2>จุดเด่นของเว็บไซต์นี้</h2>
        <div class="grid">
            <div class="card">
                <h3>🎨 การออกแบบสวยงาม</h3>
                <p>ใช้โทนสีที่สบายตาและสื่อความหมายได้ชัดเจนตามหลักการออกแบบ UX/UI</p>
            </div>
            <div class="card">
                <h3>⚡ เร็วมาก</h3>
                <p>โค้ดเบาและโหลดง่าย ช่วยให้เว็บไซต์ทำงานลื่นไหลในทุกอุปกรณ์</p>
            </div>
            <div class="card">
                <h3>📱 รองรับทุกสเกลย์</h3>
                <p>ออกแบบให้รองรับการแสดงผลบนมือถือ แท็บเล็ต และคอมพิวเตอร์ได้ครบถ้วน</p>
            </div>
        </div>
    </section>

    <footer>
        <p>&copy; 2023 เว็บไซต์ของ Fir s. ออกแบบโดย ThaiMate</p>
    </footer>

</body>
</html>