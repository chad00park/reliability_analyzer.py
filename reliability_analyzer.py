import os
import re
import sys
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# 한글 깨짐 방지를 위한 윈도우 기본 폰트 설정
import matplotlib.font_manager as fm
try:
    font_location = "C:/Windows/Fonts/malgun.ttf"
    font_name = fm.FontProperties(fname=font_location).get_name()
    matplotlib.rc('font', family=font_name)
except:
    pass

class DataAnalysisApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reliability Data Analyzer (정밀 데이터 분석 프로그램)")
        self.geometry("1400x950")
        
        # 데이터 관리 변수
        self.raw_files_data = {}  
        self.sorted_filenames = []
        self.parameter_list = []
        self.selected_parameters = []
        self.undo_history = []
        self.custom_point_colors = {}
        
        self.init_upload_menu()
        
    def init_upload_menu(self):
        for widget in self.winfo_children():
            widget.destroy()
            
        self.upload_frame = tk.Frame(self, pady=50)
        self.upload_frame.pack(expand=True, fill=tk.BOTH)
        
        lbl_title = tk.Label(self.upload_frame, text="Step 1: Data Upload (데이터 업로드)", font=("Arial", 16, "bold"))
        lbl_title.pack(pady=10)
        
        lbl_desc = tk.Label(self.upload_frame, text="시간 순서 또는 Read-out 순서의 Excel / CSV 파일들을 일괄 선택하세요.", font=("Arial", 11))
        lbl_desc.pack(pady=5)
        
        btn_upload = tk.Button(self.upload_frame, text="파일 찾아보기 (Multi-Upload)", font=("Arial", 12, "bold"), bg="#2b579a", fg="white", padx=20, pady=10, command=self.handle_file_upload)
        btn_upload.pack(pady=20)
        
        self.lbl_status = tk.Label(self.upload_frame, text="대기 중...", font=("Arial", 10, "italic"), fg="gray")
        self.lbl_status.pack(pady=5)

    def extract_sort_key(self, filename):
        numbers = re.findall(r'\d+', filename)
        return int(numbers[0]) if numbers else 0

    def handle_file_upload(self):
        files = filedialog.askopenfilenames(
            title="분석할 파일들을 선택하세요 (최대 20개)",
            filetypes=[("Data Files", "*.csv *.xlsx *.xls")]
        )
        if not files:
            return
            
        if len(files) > 20:
            messagebox.showerror("오류", "파일은 20개 이하이어야 합니다.")
            return
            
        popup_prep = tk.Toplevel(self)
        popup_prep.title("알림")
        popup_prep.geometry("300x120")
        popup_prep.transient(self)
        popup_prep.grab_set()
        
        lbl_prep = tk.Label(popup_prep, text="분석 준 비 중", font=("Arial", 14, "bold"), pady=30)
        lbl_prep.pack()
        self.update()
        
        try:
            sorted_paths = sorted(files, key=lambda x: self.extract_sort_key(os.path.basename(x)))
            temp_files_data = {}
            all_detected_params = set()
            
            for path in sorted_paths:
                fname = os.path.basename(path)
                if fname.endswith('.csv'):
                    df = pd.read_csv(path, header=[0, 1])
                else:
                    df = pd.read_excel(path, header=[0, 1])
                
                num_rows = len(df)
                num_cols = len(df.columns) - 1
                    
                if num_rows > 500 or num_cols > 100:
                    popup_prep.destroy()
                    messagebox.showerror("오류", "시료수(500이하) 또는 Parameter수(100이하) 제한을 초과했습니다.")
                    return
                
                unit_col_name = df.columns[0]
                units_list = df[unit_col_name].astype(str).tolist()
                
                param_dict = {}
                for col in df.columns[1:]:
                    p_name = col[0]
                    p_unit = col[1] if not pd.isna(col[1]) else ""
                    if "cont" in p_name.lower() or "contact" in p_name.lower():
                        continue
                        
                    vals = pd.to_numeric(df[col], errors='coerce').tolist()
                    param_dict[p_name] = {
                        'unit': p_unit,
                        'values': vals,
                        'units_map': units_list.copy()
                    }
                    all_detected_params.add(p_name)
                    
                temp_files_data[fname] = {
                    'raw_df': df,
                    'units': units_list,
                    'params': param_dict
                }
            
            self.raw_files_data = temp_files_data
            self.sorted_filenames = [os.path.basename(p) for p in sorted_paths]
            self.parameter_list = sorted(list(all_detected_params))
            
            popup_prep.destroy()
            self.init_analysis_menu()
            
        except Exception as e:
            popup_prep.destroy()
            messagebox.showerror("에러 발생", f"파일을 읽는 중 에러가 발생했습니다:\n{str(e)}")

    def init_analysis_menu(self):
        for widget in self.winfo_children():
            widget.destroy()
            
        top_frame = tk.Frame(self, bg="#f4f4f4", pady=10, padx=10)
        top_frame.pack(fill=tk.X, side=tk.TOP)
        
        tk.Label(top_frame, text="Parameter 선택 (Drop-down):", font=("Arial", 11, "bold"), bg="#f4f4f4").pack(side=tk.LEFT, padx=5)
        
        self.combo_options = ["전체 선택"] + self.parameter_list
        self.param_var = tk.StringVar()
        self.combo_param = ttk.Combobox(top_frame, textvariable=self.param_var, values=self.combo_options, width=30, state="readonly")
        self.combo_param.pack(side=tk.LEFT, padx=5)
        self.combo_param.current(1 if len(self.combo_options) > 1 else 0)
        
        btn_apply = tk.Button(top_frame, text="그래프 그리기", font=("Arial", 10, "bold"), bg="#107c41", fg="white", command=self.render_analysis_graphs)
        btn_apply.pack(side=tk.LEFT, padx=10)
        
        self.btn_undo = tk.Button(top_frame, text="↩️ 되돌리기 (Undo)", font=("Arial", 10), state=tk.DISABLED, command=self.trigger_undo)
        self.btn_undo.pack(side=tk.LEFT, padx=5)
        
        bottom_frame = tk.Frame(self, bg="#e6e6e6", pady=8, padx=10)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        btn_pdf = tk.Button(bottom_frame, text="결과물 PDF 파일로 저장", font=("Arial", 11, "bold"), bg="#d24726", fg="white", padx=15, command=self.export_plots_to_pdf)
        btn_pdf.pack(side=tk.RIGHT, padx=10)
        
        container = tk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(container)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.render_analysis_graphs(first_trigger=True)

    def update_undo_button_state(self):
        if self.undo_history:
            self.btn_undo.config(state=tk.NORMAL)
        else:
            self.btn_undo.config(state=tk.DISABLED)

    def render_analysis_graphs(self, first_trigger=False):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
            
        chosen = self.param_var.get()
        if chosen == "전체 선택":
            self.selected_parameters = self.parameter_list.copy()
        else:
            self.selected_parameters = [chosen] if chosen else []
            
        if not self.selected_parameters:
            return
            
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        
        # 1. Line Charts 섹션 (기존 유지)
        st_label1 = tk.Label(self.scrollable_frame, text="■ 시간별 데이터 변화 추이 (Line Charts)", font=("Arial", 14, "bold"), fg="#111", pady=10)
        st_label1.pack(anchor="w", padx=10)
        
        for param in self.selected_parameters:
            unit_str = ""
            for fn in self.sorted_filenames:
                if param in self.raw_files_data[fn]['params']:
                    unit_str = self.raw_files_data[fn]['params'][param]['unit']
                    break
            
            fig, ax = plt.subplots(figsize=(13.0, 1.8))
            
            for f_idx, filename in enumerate(self.sorted_filenames):
                if param not in self.raw_files_data[filename]['params']: continue
                p_info = self.raw_files_data[filename]['params'][param]
                x_units = p_info['units_map']
                y_vals = p_info['values']
                
                plot_x, plot_y, plot_colors = [], [], []
                for idx, (ux, uy) in enumerate(zip(x_units, y_vals)):
                    if uy is None or np.isnan(uy): continue
                    plot_x.append(str(ux))
                    plot_y.append(uy)
                    
                    c_key = (param, filename, str(ux))
                    plot_colors.append(self.custom_point_colors.get(c_key, colors[f_idx % len(colors)]))
            
                if plot_x:
                    ax.plot(plot_x, plot_y, linestyle='-', color=colors[f_idx % len(colors)], alpha=0.6, zorder=1)
                    ax.scatter(plot_x, plot_y, color=plot_colors, s=25, label=filename, zorder=2, picker=True)
            
            ax.set_title(f"{param} [{unit_str}]", fontdict={'fontsize': 11, 'weight': 'bold'})
            ax.set_xlabel("Unit #", fontsize=9)
            ax.set_ylabel(param, fontsize=9)
            ax.tick_params(axis='both', labelsize=8)
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(True, linestyle=":", alpha=0.5)
            
            canvas = FigureCanvasTkAgg(fig, master=self.scrollable_frame)
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill=tk.X, padx=15, pady=5)
            canvas.mpl_connect('pick_event', lambda event, p=param: self.on_point_picked(event, p))
            
            ctrl_f = tk.Frame(self.scrollable_frame, bg="#fafafa")
            ctrl_f.pack(fill=tk.X, padx=20, pady=2)
            tk.Label(ctrl_f, text="Y축 최소:", font=("Arial", 8), bg="#fafafa").pack(side=tk.LEFT)
            en_min = tk.Entry(ctrl_f, width=6, font=("Arial", 8))
            en_min.pack(side=tk.LEFT, padx=2)
            tk.Label(ctrl_f, text="최대:", font=("Arial", 8), bg="#fafafa").pack(side=tk.LEFT)
            en_max = tk.Entry(ctrl_f, width=6, font=("Arial", 8))
            en_max.pack(side=tk.LEFT, padx=2)
            
            def apply_axis(a=ax, c=canvas, emin=en_min, emax=en_max):
                try:
                    if emin.get(): a.set_ylim(bottom=float(emin.get()))
                    if emax.get(): a.set_ylim(top=float(emax.get()))
                    c.draw()
                except ValueError: pass
            tk.Button(ctrl_f, text="축 조정", font=("Arial", 8), command=apply_axis).pack(side=tk.LEFT, padx=5)

        # 2. Box Plots 섹션 (★프로그램 UI 화면 내 가로 4열 배치 완벽 반영★)
        st_label2 = tk.Label(self.scrollable_frame, text="■ Read-out별 데이터 산포 비교 (Box Plots & Statistics)", font=("Arial", 14, "bold"), fg="#111", pady=15)
        st_label2.pack(anchor="w", padx=10)
        
        # 프로그램 화면 내부에서 그리드 가로 배치를 담당할 컨테이너
        grid_container = tk.Frame(self.scrollable_frame, bg="#f0f0f0")
        grid_container.pack(fill=tk.X, padx=15, pady=5)
        
        for p_idx, param in enumerate(self.selected_parameters):
            row_idx = p_idx // 4
            col_idx = p_idx % 4
            
            # 개별 컴포넌트 프레임 (그리드 주입)
            box_block = tk.Frame(grid_container, bd=1, relief=tk.GROOVE, pady=10, padx=10, bg="white", width=320)
            box_block.grid(row=row_idx, column=col_idx, padx=8, pady=10, sticky="nsew")
            
            fig, ax = plt.subplots(figsize=(3.2, 3.2))
            box_data, active_labels, box_colors, stat_strings = [], [], [], []
            
            for f_idx, filename in enumerate(self.sorted_filenames):
                if param not in self.raw_files_data[filename]['params']: continue
                p_info = self.raw_files_data[filename]['params'][param]
                vals = [v for v in p_info['values'] if v is not None and not np.isnan(v)]
                
                box_data.append(vals)
                active_labels.append(filename)
                box_colors.append(colors[f_idx % len(colors)])
                
                if vals:
                    stat_strings.append(f"[{filename}]\nMin:{np.min(vals):.2f} | Max:{np.max(vals):.2f}\nAVG:{np.mean(vals):.2f} | s/s:{len(vals)} | STD:{np.std(vals):.2f}")
                else:
                    stat_strings.append(f"[{filename}]\nNo Data")
            
            unit_str = ""
            for fn in self.sorted_filenames:
                if param in self.raw_files_data[fn]['params']:
                    unit_str = self.raw_files_data[fn]['params'][param]['unit']
                    break
                    
            if box_data and any(len(b) > 0 for b in box_data):
                try:
                    bp = ax.boxplot(box_data, tick_labels=active_labels, patch_artist=True, showmeans=False,
                                    medianprops=dict(color="black", linewidth=1.2),
                                    flierprops=dict(marker='o', markerfacecolor='gray', markersize=3, linestyle='none'))
                except TypeError:
                    bp = ax.boxplot(box_data, labels=active_labels, patch_artist=True, showmeans=False,
                                    medianprops=dict(color="black", linewidth=1.2),
                                    flierprops=dict(marker='o', markerfacecolor='gray', markersize=3, linestyle='none'))
                
                for patch, color in zip(bp['boxes'], box_colors):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.7)
            
            ax.set_title(f"{param} [{unit_str}]", fontdict={'fontsize': 10, 'weight': 'bold'})
            ax.tick_params(axis='x', labelsize=8, rotation=20)
            ax.tick_params(axis='y', labelsize=8)
            ax.grid(True, linestyle=":", alpha=0.4)
            fig.tight_layout()
            
            # 그래프 배치
            canvas_box = FigureCanvasTkAgg(fig, master=box_block)
            canvas_box_widget = canvas_box.get_tk_widget()
            canvas_box_widget.pack(side=tk.TOP, fill=tk.X)
            canvas_box.draw()
            
            # 그래프 바로 아래에 통계값 박스 배치
            stat_frame = tk.Frame(box_block, bg="#fafafa", bd=1, relief=tk.SUNKEN, padx=8, pady=8)
            stat_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=5)
            
            for st_txt in stat_strings:
                tk.Label(stat_frame, text=st_txt, font=("Consolas", 8), bg="#fafafa", fg="#333", justify=tk.LEFT, anchor="w").pack(fill=tk.X, pady=3)

        # 모든 열이 균등한 가로 사이즈 비율을 갖도록 크기 가중치 보정
        for c in range(4):
            grid_container.column_configure(c, weight=1)

        self.update_undo_button_state()
        if first_trigger:
            self.after(200, lambda: messagebox.showinfo("안내", "분석하고자 하는 parameter를 선택하세요"))

    def on_point_picked(self, event, param_name):
        line = event.artist
        filename = line.get_label()
        ind = event.ind[0]
        
        p_info = self.raw_files_data[filename]['params'][param_name]
        active_indices = [i for i, v in enumerate(p_info['values']) if v is not None and not np.isnan(v)]
        if ind >= len(active_indices): return
        real_idx = active_indices[ind]
        
        unit_id = str(p_info['units_map'][real_idx])
        raw_val = p_info['values'][real_idx]
        
        popup_act = tk.Toplevel(self)
        popup_act.title("데이터 포인트 제어")
        popup_act.geometry("380x180")
        popup_act.transient(self)
        popup_act.grab_set()
        
        lbl = tk.Label(popup_act, text=f"선택 포인트 - 파일: {filename}\nParameter: {param_name}\nUnit 번호: {unit_id} | 값: {raw_val}", font=("Arial", 10))
        lbl.pack(pady=10)
        
        btn_frame = tk.Frame(popup_act)
        btn_frame.pack(pady=5)
        
        def change_color():
            self.custom_point_colors[(param_name, filename, unit_id)] = "magenta"
            self.undo_history.append(('COLOR', param_name, filename, unit_id, real_idx, raw_val, False))
            popup_act.destroy()
            self.render_analysis_graphs()
            
        def delete_point_only():
            p_info['values'][real_idx] = None
            self.undo_history.append(('DELETE_POINT', param_name, filename, unit_id, real_idx, raw_val, False))
            popup_act.destroy()
            self.render_analysis_graphs()
            
        def delete_unit_axis():
            saved_states = []
            for fn in self.sorted_filenames:
                if param_name in self.raw_files_data[fn]['params']:
                    f_p_info = self.raw_files_data[fn]['params'][param_name]
                    if unit_id in f_p_info['units_map']:
                        u_idx = f_p_info['units_map'].index(unit_id)
                        old_v = f_p_info['values'][u_idx]
                        f_p_info['values'][u_idx] = None
                        saved_states.append((fn, u_idx, old_v))
            
            self.undo_history.append(('DELETE_UNIT', param_name, filename, unit_id, real_idx, saved_states, True))
            popup_act.destroy()
            self.render_analysis_graphs()
            
        tk.Button(btn_frame, text="🎨 점 색상 변경 (Magenta)", bg="#e17055", fg="white", command=change_color, width=22).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(btn_frame, text="🗑️ 해당 데이터만 삭제", bg="#d63031", fg="white", command=delete_point_only, width=22).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(btn_frame, text="❌ X축 Unit 번호 및 전체 삭제", bg="#2d3436", fg="white", command=delete_unit_axis, width=46).grid(row=1, column=0, columnspan=2, padx=5, pady=5)

    def trigger_undo(self):
        if not self.undo_history: return
        last_action = self.undo_history.pop()
        action_type = last_action[0]
        
        if action_type == 'COLOR':
            param_name, filename, unit_id = last_action[1], last_action[2], last_action[3]
            key = (param_name, filename, unit_id)
            if key in self.custom_point_colors: del self.custom_point_colors[key]
        elif action_type == 'DELETE_POINT':
            param_name, filename, unit_id, real_idx, raw_val = last_action[1], last_action[2], last_action[3], last_action[4], last_action[5]
            self.raw_files_data[filename]['params'][param_name]['values'][real_idx] = raw_val
        elif action_type == 'DELETE_UNIT':
            param_name = last_action[1]
            saved_states = last_action[5]
            for fn, u_idx, old_v in saved_states:
                self.raw_files_data[fn]['params'][param_name]['values'][u_idx] = old_v
                
        messagebox.showinfo("되돌리기", "이전 작업이 성공적으로 복구되었습니다.")
        self.render_analysis_graphs()

    def export_plots_to_pdf(self):
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF Documents", "*.pdf")])
        if not save_path: return
        
        try:
            from matplotlib.backends.backend_pdf import PdfPages
            colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
            
            with PdfPages(save_path) as pdf:
                # Part 1: Line Charts 모아찍기 (한 페이지당 가로 모드 최대 4개)
                for chunk_idx in range(0, len(self.selected_parameters), 4):
                    fig = plt.figure(figsize=(11, 8.5))
                    plt.suptitle("Reliability Trend Report - Line Charts", fontsize=14, weight='bold', y=0.96)
                    
                    chunk_params = self.selected_parameters[chunk_idx:chunk_idx+4]
                    for sub_idx, param in enumerate(chunk_params):
                        ax = fig.add_subplot(4, 1, sub_idx + 1)
                        
                        unit_str = ""
                        for fn in self.sorted_filenames:
                            if param in self.raw_files_data[fn]['params']:
                                unit_str = self.raw_files_data[fn]['params'][param]['unit']
                                break
                                
                        for f_idx, filename in enumerate(self.sorted_filenames):
                            if param not in self.raw_files_data[filename]['params']: continue
                            p_info = self.raw_files_data[filename]['params'][param]
                            plot_x = [str(ux) for ux, uy in zip(p_info['units_map'], p_info['values']) if uy is not None and not np.isnan(uy)]
                            plot_y = [uy for uy in p_info['values'] if uy is not None and not np.isnan(uy)]
                            if plot_x:
                                ax.plot(plot_x, plot_y, '-o', label=filename, color=colors[f_idx % len(colors)], markersize=2.5, linewidth=1)
                        
                        ax.set_title(f"{param} [{unit_str}]", fontsize=9, pad=3)
                        ax.grid(True, linestyle=":", alpha=0.5)
                        ax.tick_params(labelsize=7)
                        if sub_idx == 0:
                            ax.legend(loc="upper right", fontsize=6, ncol=3)
                            
                    fig.tight_layout(rect=[0, 0, 1, 0.93])
                    pdf.savefig(fig)
                    plt.close(fig)
                
                # Part 2: Box Plots 모아찍기 (한 페이지당 가로 모드 최대 4개)
                for chunk_idx in range(0, len(self.selected_parameters), 4):
                    fig = plt.figure(figsize=(11, 8.5))
                    plt.suptitle("Reliability Distribution Report - Box Plots", fontsize=14, weight='bold', y=0.96)
                    
                    chunk_params = self.selected_parameters[chunk_idx:chunk_idx+4]
                    for sub_idx, param in enumerate(chunk_params):
                        ax = fig.add_subplot(1, 4, sub_idx + 1)
                        
                        box_data, active_labels = [], []
                        for filename in self.sorted_filenames:
                            if param in self.raw_files_data[filename]['params']:
                                vals = [v for v in self.raw_files_data[filename]['params'][param]['values'] if v is not None and not np.isnan(v)]
                                box_data.append(vals)
                                active_labels.append(filename)
                        
                        unit_str = ""
                        for fn in self.sorted_filenames:
                            if param in self.raw_files_data[fn]['params']:
                                unit_str = self.raw_files_data[fn]['params'][param]['unit']
                                break
                                
                        if box_data and any(len(b) > 0 for b in box_data):
                            try:
                                ax.boxplot(box_data, tick_labels=active_labels)
                            except TypeError:
                                ax.boxplot(box_data, labels=active_labels)
                                
                        ax.set_title(f"{param}\n[{unit_str}]", fontsize=9)
                        ax.grid(True, linestyle=":", alpha=0.4)
                        ax.tick_params(axis='x', labelsize=7, rotation=30)
                        ax.tick_params(axis='y', labelsize=7)
                        
                    fig.tight_layout(rect=[0, 0, 1, 0.92])
                    pdf.savefig(fig)
                    plt.close(fig)
                    
            messagebox.showinfo("PDF 내보내기", f"가로 보기 양식 리포트가 생성되었습니다:\n{save_path}")
        except Exception as e:
            messagebox.showerror("PDF 에러", f"PDF 생성 중 에러 발생: {str(e)}")

if __name__ == "__main__":
    app = DataAnalysisApp()
    app.mainloop()
