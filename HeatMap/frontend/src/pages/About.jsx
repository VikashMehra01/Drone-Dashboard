import { Shield, BookOpen, Github, Users } from 'lucide-react'
import iitRoparLogo from '../assets/iit-ropar.svg'

export default function About() {
    return (
        <div className="about-page">
            <div className="about-header">
                <div className="about-logo">
                    <img src={iitRoparLogo} alt="IIT Ropar Logo" style={{ width: '80%', height: '80%', objectFit: 'contain' }} />
                </div>
                <h1>SkyWatch</h1>
                <p className="about-subtitle">Drone Surveillance Portal</p>
                <p style={{ color: 'var(--color-text-secondary)', marginTop: '8px', fontSize: '14px', fontWeight: '500' }}>Indian Institute of Technology (IIT) Ropar</p>
            </div>

            <div className="about-content">
                <section className="about-section">
                    <div className="section-header">
                        <BookOpen size={24} />
                        <h2>About the Project</h2>
                    </div>
                    <p>
                        SkyWatch is a smart surveillance system that helps police officers monitor crowds and public areas using drones.
                        It automatically counts people in real-time and shows you exactly where crowds are gathering.
                        This helps you make better decisions about crowd control, safety, and emergency response.
                    </p>
                    <p>
                        The system works by analyzing live video feeds from drones flying overhead. It can tell you how many people
                        are in different areas, show you heat maps of crowd density, and alert you when crowds get too large.
                        Whether it's a festival, protest, or public event, SkyWatch gives you the information you need to keep everyone safe.
                    </p>
                </section>

                <section className="about-section">
                    <div className="section-header">
                        <Users size={24} />
                        <h2>Manual: How to Use SkyWatch</h2>
                    </div>
                    <div className="usage-guide">
                        <h3>Getting Started</h3>
                        <p>
                            When you open SkyWatch, you'll see the main dashboard. Use the menu on the left side to navigate between different sections.
                            The system is designed to be easy to use - just click on what you want to see.
                        </p>

                        <h3>Dashboard - Your Main Overview</h3>
                        <ul>
                            <li><strong>Map View:</strong> Shows all active drones and their locations. Click on drone markers to see details.</li>
                            <li><strong>Crowd Density Stats:</strong> Displays current crowd counts and density levels across all monitored areas.</li>
                            <li><strong>Drone Status:</strong> See which drones are active, their battery levels, and any issues.</li>
                            <li><strong>Alerts:</strong> Important notifications about crowded areas or drone problems appear here.</li>
                        </ul>

                        <h3>Live Feeds - Watch Real-Time Video</h3>
                        <ul>
                            <li><strong>Video Streams:</strong> View live video from each drone as it flies and monitors areas.</li>
                            <li><strong>Multiple Cameras:</strong> Switch between different drone feeds to see various locations.</li>
                            <li><strong>Full Screen:</strong> Click on any video to make it larger for better viewing.</li>
                        </ul>

                        <h3>Analytics - Understand Trends and History</h3>
                        <ul>
                            <li><strong>Crowd Trends:</strong> See how crowd sizes change over time with easy-to-read charts.</li>
                            <li><strong>Historical Data:</strong> Review past events and crowd patterns to prepare for similar situations.</li>
                            <li><strong>Density Maps:</strong> Visual heat maps show where people gather most densely.</li>
                            <li><strong>Reports:</strong> Generate summary reports of crowd activity for your records.</li>
                        </ul>

                        <h3>Understanding the Information</h3>
                        <ul>
                            <li><strong>Green/Yellow/Red Indicators:</strong> Colors show crowd density levels - green is safe, red means attention needed.</li>
                            <li><strong>Numbers:</strong> Exact crowd counts help you understand the scale of gatherings.</li>
                            <li><strong>Locations:</strong> GPS coordinates and area names tell you exactly where issues are occurring.</li>
                            <li><strong>Time Stamps:</strong> All information shows when it was recorded, so you know how current it is.</li>
                        </ul>

                        <div className="manual-legend-panel" style={{ marginTop: '24px', background: 'var(--color-bg-secondary)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--color-border)' }}>
                            <h4 style={{ marginBottom: '12px', fontSize: '15px', color: 'var(--color-text-primary)' }}>Crowd Level Color Legend</h4>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div className="legend-dot" style={{ background: '#1565c0', width: '12px', height: '12px', borderRadius: '50%' }} />
                                    <span style={{ color: 'var(--color-text-secondary)', fontSize: '14px' }}><strong>Low (Blue)</strong> - Safe, minimal crowd</span>
                                </div>
                                <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div className="legend-dot" style={{ background: '#4caf50', width: '12px', height: '12px', borderRadius: '50%' }} />
                                    <span style={{ color: 'var(--color-text-secondary)', fontSize: '14px' }}><strong>Moderate (Green)</strong> - Normal crowd</span>
                                </div>
                                <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div className="legend-dot" style={{ background: '#ffeb3b', width: '12px', height: '12px', borderRadius: '50%' }} />
                                    <span style={{ color: 'var(--color-text-secondary)', fontSize: '14px' }}><strong>High (Yellow)</strong> - Dense crowd, monitor closely</span>
                                </div>
                                <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div className="legend-dot" style={{ background: '#ff9800', width: '12px', height: '12px', borderRadius: '50%' }} />
                                    <span style={{ color: 'var(--color-text-secondary)', fontSize: '14px' }}><strong>Very High (Orange)</strong> - Very dense, warning</span>
                                </div>
                                <div className="legend-item" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div className="legend-dot" style={{ background: '#f44336', width: '12px', height: '12px', borderRadius: '50%' }} />
                                    <span style={{ color: 'var(--color-text-secondary)', fontSize: '14px' }}><strong>Critical (Red)</strong> - Exceeds expected limits, immediate attention needed</span>
                                </div>
                            </div>
                        </div>

                        <h3 style={{ marginTop: '24px' }}>Tips for Effective Use</h3>
                        <ul>
                            <li>Check the dashboard first to get an overview of all activity</li>
                            <li>Use the map to understand where drones are positioned</li>
                            <li>Set up alerts for areas that need special attention</li>
                            <li>Review analytics after events to improve future planning</li>
                            <li>Regularly monitor battery levels and drone status</li>
                        </ul>
                    </div>
                </section>

                <section className="about-section">
                    <div className="section-header">
                        <Github size={24} />
                        <h2>Contributors</h2>
                    </div>
                    <div className="contributors-section">
                        <div className="contributors-group">
                            <h3>Developers</h3>
                            <div className="contributors-list">
                                <div className="contributor">
                                    <span className="contributor-name">Aamod Jain</span>
                                </div>
                                <div className="contributor">
                                    <span className="contributor-name">Aditya Gupta</span>
                                </div>
                                <div className="contributor">
                                    <span className="contributor-name">Raghav Jha</span>
                                </div>
                                <div className="contributor">
                                    <span className="contributor-name">Vikash Kumar</span>
                                </div>
                            </div>
                        </div>

                        <div className="contributors-group">
                            <h3>Project Supervisors</h3>
                            <div className="contributors-list">
                                <div className="contributor">
                                    <span className="contributor-name">Dr. Puneet Goyal</span>
                                    <span className="contributor-role">Professor</span>
                                </div>
                                <div className="contributor">
                                    <span className="contributor-name">Dr. Shashi Shekhar Jha</span>
                                    <span className="contributor-role">Professor</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>
            </div>
        </div>
    )
}